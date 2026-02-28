import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
import json
from datetime import datetime, timedelta
from io import BytesIO
import pdfplumber

IMAP_SERVER = "imap.gmail.com"

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SENT_FILE = "sent_rsts.json"
LAST_SUMMARY_FILE = "last_summary.txt"


# ---------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------

def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def format_12h(dt):
    if not dt:
        return "Time N/A"
    return dt.strftime("%d-%b-%y | %I:%M %p")


# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("[ERR] Telegram failed:", e)


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def safe_decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for p, enc in parts:
        if isinstance(p, bytes):
            out.append(p.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(p)
    return "".join(out)


def pick(text, pattern):
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def normalize(s):
    return re.sub(r"\s+", " ", s.strip()) if s else ""


def clean_material(m):
    if not m:
        return ""
    return re.sub(r"CELL.*", "", m, flags=re.IGNORECASE).strip()


def parse_dt(s):
    if not s:
        return None
    fmts = [
        "%d-%b-%y %I:%M:%S %p",
        "%d-%b-%Y %I:%M:%S %p",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None


# ---------------------------------------------------------
# PDF EXTRACTION
# ---------------------------------------------------------

def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        print("[ERR] PDF read failure")
        return {}

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    material = normalize(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL"))
    material = clean_material(material)

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)"),
        "Material": material,
        "GrossKg": pick(text, r"Gross\.?:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.?:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross.*?Kgs.*?" + dt_pat),
        "TareDT": pick(text, r"Tare.*?Kgs.*?" + dt_pat)
    }


# ---------------------------------------------------------
# EMAIL SCAN
# ---------------------------------------------------------

def scan_last_50_emails():
    yard = {}

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    _, data = mail.uid("search", None, "ALL")
    uids = [int(x) for x in data[0].split()]
    recent = uids[-50:]

    for uid in recent:
        _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = safe_decode(msg.get("Subject")).upper()
        if "WEIGH" not in subject and "SLIP" not in subject:
            continue

        for part in msg.walk():
            if "pdf" in part.get_content_type():
                info = extract_from_pdf(part.get_payload(decode=True))
                if not info or not info.get("RST"):
                    continue

                rst = info["RST"]

                if rst not in yard:
                    yard[rst] = {
                        "RST": rst,
                        "Vehicle": info["Vehicle"],
                        "Party": info["Party"],
                        "Material": info["Material"],
                        "Gross": None,
                        "GrossTime": None,
                        "Tare": None,
                        "TareTime": None
                    }

                if info["GrossKg"]:
                    yard[rst]["Gross"] = int(info["GrossKg"])
                    yard[rst]["GrossTime"] = parse_dt(info["GrossDT"])

                if info["TareKg"]:
                    yard[rst]["Tare"] = int(info["TareKg"])
                    yard[rst]["TareTime"] = parse_dt(info["TareDT"])

    mail.logout()
    print(f"[SCAN] {len(yard)} RST entries built")
    return yard


# ---------------------------------------------------------
# MEMORY
# ---------------------------------------------------------

def load_sent():
    if not os.path.exists(SENT_FILE):
        return set()
    try:
        return set(json.load(open(SENT_FILE)))
    except:
        return set()


def save_sent(s):
    json.dump(list(s), open(SENT_FILE, "w"))


# ---------------------------------------------------------
# ALERT SENDER
# ---------------------------------------------------------

def send_alert(rst, d):
    gross = d["Gross"]
    tare = d["Tare"]

    # Determine first/second
    times = []
    if tare and d["TareTime"]:
        times.append(("Tare", tare, d["TareTime"]))
    if gross and d["GrossTime"]:
        times.append(("Gross", gross, d["GrossTime"]))

    times.sort(key=lambda x: x[2])

    if len(times) == 1:
        # ENTRY ONLY
        ttype, wt, tdt = times[0]
        pending = "Gross" if ttype == "Tare" else "Tare"

        msg = (
            f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
            f"🧾 RST : {rst}   🚛 {d['Vehicle']}\n"
            f"🏢 PARTY : {d['Party']}\n"
            f"🌾 MATERIAL : {d['Material']}\n\n"
            f"⟪ FIRST WEIGHMENT ⟫\n"
            f"⚖ {ttype} : {wt} Kg\n"
            f"🕒 {format_12h(tdt)}\n\n"
            f"⟪ SECOND WEIGHMENT ⟫ Pending\n"
            f"⚖ {pending} : Pending\n\n"
            f"🟡 STATUS : VEHICLE INSIDE YARD"
        )

    else:
        # COMPLETION
        (t1, w1, dt1), (t2, w2, dt2) = times
        net = abs(w2 - w1)

        msg = (
            f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
            f"🧾 RST : {rst}   🚛 {d['Vehicle']}\n"
            f"🏢 PARTY : {d['Party']}\n"
            f"🌾 MATERIAL : {d['Material']}\n\n"
            f"⟪ FIRST WEIGHMENT ⟫\n"
            f"⚖ {t1} : {w1} Kg\n"
            f"🕒 {format_12h(dt1)}\n\n"
            f"⟪ SECOND WEIGHMENT ⟫\n"
            f"⚖ {t2} : {w2} Kg\n"
            f"🕒 {format_12h(dt2)}\n\n"
            f"🔵 NET LOAD : {net} Kg\n\n"
            f"🟢 STATUS : WEIGHMENT COMPLETED"
        )

    send_telegram(msg)


# ---------------------------------------------------------
# DAILY SUMMARY
# ---------------------------------------------------------

def send_daily_summary(yard):
    now = now_ist()
    today = now.strftime("%Y-%m-%d")

    last = ""
    if os.path.exists(LAST_SUMMARY_FILE):
        last = open(LAST_SUMMARY_FILE).read().strip()

    if last == today:
        return

    if not (now.hour == 10 and 0 <= now.minute <= 5):
        return

    msg = f"📊 TODAY’S SUMMARY ({now.strftime('%d-%b %I:%M %p')})\n\n"

    # Completed first
    for rst, d in yard.items():
        if d["Gross"] and d["Tare"]:
            times = sorted(
                [("Tare", d["Tare"], d["TareTime"]),
                 ("Gross", d["Gross"], d["GrossTime"])],
                key=lambda x: x[2]
            )
            (_, _, dt1), (_, _, dt2) = times
            net = abs(d["Gross"] - d["Tare"])
            msg += (
                f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']} | "
                f"IN {format_12h(dt1)} | OUT {format_12h(dt2)} | NET {net} Kg\n"
            )

    # Pending
    for rst, d in yard.items():
        if (d["Gross"] and not d["Tare"]) or (d["Tare"] and not d["Gross"]):
            wt = d["Gross"] or d["Tare"]
            dt = d["GrossTime"] or d["TareTime"]
            pending = "Tare" if d["Gross"] else "Gross"
            msg += (
                f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']} | "
                f"IN {format_12h(dt)} | Pending {pending}\n"
            )

    send_telegram(msg)
    open(LAST_SUMMARY_FILE, "w").write(today)
    print("[SUMMARY] Daily summary sent")


# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------

if __name__ == "__main__":
    sent = load_sent()

    while True:
        try:
            yard = scan_last_50_emails()

            for rst, d in yard.items():
                if rst not in sent:
                    send_alert(rst, d)
                    sent.add(rst)

            save_sent(sent)
            send_daily_summary(yard)

        except Exception as e:
            print("[ERR]", e)

        time.sleep(30)