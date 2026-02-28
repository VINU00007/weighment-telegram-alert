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

SENT_ENTRY = "SentEntryRSTs.json"
SENT_COMPLETE = "SentCompletionRSTs.json"

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
# TELEGRAM SEND
# ---------------------------------------------------------

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("[ERR] Telegram send failed:", e)

# ---------------------------------------------------------
# TEXT HELPERS
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
    m = m.replace("CELL", "")
    m = m.replace("NO", "")
    return normalize(m)

# ---------------------------------------------------------
# DATE PARSER
# ---------------------------------------------------------

def parse_dt(s):
    if not s:
        return None
    fmts = [
        "%d-%b-%y %I:%M:%S %p",
        "%d-%b-%Y %I:%M:%S %p"
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None

# ---------------------------------------------------------
# PDF EXTRACTOR
# ---------------------------------------------------------

def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        print("[ERR] PDF read failure")
        return {}

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    mat = pick(text, r"MATERIAL\s*:\s*(.+?)\s+(?:CELL|NO|$)")
    mat = clean_material(mat)

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)"),
        "Material": mat,
        "GrossKg": pick(text, r"Gross\.?:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.?:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross.*?Kgs.*?" + dt_pat),
        "TareDT": pick(text, r"Tare.*?Kgs.*?" + dt_pat)
    }

# ---------------------------------------------------------
# EMAIL SCANNER (LAST 200 EMAILS)
# ---------------------------------------------------------

def scan_last_200_emails():
    yard = {}

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    _, data = mail.uid("search", None, "ALL")
    uids = [int(x) for x in data[0].split()]

    # Scan last 200 emails
    recent = uids[-200:]

    for uid in recent:
        _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = safe_decode(msg.get("Subject")).upper()

        if "WEIGH" not in subject and "SLIP" not in subject:
            continue

        for part in msg.walk():
            if "pdf" in part.get_content_type():
                pdf_bytes = part.get_payload(decode=True)
                info = extract_from_pdf(pdf_bytes)
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
# LOAD/SAVE SENT FILES
# ---------------------------------------------------------

def load_set(file):
    if not os.path.exists(file):
        return set()
    try:
        return set(json.load(open(file)))
    except:
        return set()

def save_set(file, data):
    json.dump(list(data), open(file, "w"), indent=2)

# ---------------------------------------------------------
# REALTIME ALERTS
# ---------------------------------------------------------

def send_realtime_alerts(yard, sent_entry, sent_complete):

    for rst, d in yard.items():
        gross = d["Gross"]
        tare = d["Tare"]

        gross_t = d["GrossTime"]
        tare_t = d["TareTime"]

        # ENTRY ALERT
        if (gross and not tare) or (tare and not gross):

            if rst not in sent_entry:

                in_wt = gross if gross else tare
                in_time = gross_t if gross else tare_t
                in_type = "Gross" if gross else "Tare"

                msg = (
                    f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                    f"🧾 RST : {rst}   🚛 {d['Vehicle']}\n"
                    f"🏭 PARTY : {d['Party']}\n"
                    f"🌾 MATERIAL : {d['Material']}\n\n"
                    f"《 FIRST WEIGHMENT 》\n"
                    f"⚖ {in_type} : {in_wt} Kg\n"
                    f"🕒 {format_12h(in_time)}\n\n"
                    f"《 SECOND WEIGHMENT 》 Pending\n"
                    f"⚖ Gross/Tare : Pending\n\n"
                    f"🟡 STATUS : VEHICLE INSIDE YARD"
                )

                send_telegram(msg)
                sent_entry.add(rst)
                print(f"[ENTRY] Sent RST {rst}")

        # COMPLETION ALERT
        if gross and tare:

            if rst not in sent_complete:

                times = []
                if tare_t:  times.append(("Tare", tare, tare_t))
                if gross_t: times.append(("Gross", gross, gross_t))
                times = [t for t in times if t[2] is not None]

                if len(times) < 2:
                    continue

                times.sort(key=lambda x: x[2])

                (_, first_wt, t1), (_, second_wt, t2) = times
                net = abs(gross - tare)

                msg = (
                    f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                    f"🧾 RST : {rst}   🚛 {d['Vehicle']}\n"
                    f"🏭 PARTY : {d['Party']}\n"
                    f"🌾 MATERIAL : {d['Material']}\n\n"
                    f"⟪ IN  ⟫ {format_12h(t1)}\n"
                    f"⚖ First : {first_wt} Kg\n\n"
                    f"⟪ OUT ⟫ {format_12h(t2)}\n"
                    f"⚖ Second : {second_wt} Kg\n\n"
                    f"🔵 NET LOAD : {net} Kg\n"
                    f"🟢 STATUS : WEIGHMENT COMPLETED"
                )

                send_telegram(msg)
                sent_complete.add(rst)
                print(f"[COMPLETE] Sent RST {rst}")

    save_set(SENT_ENTRY, sent_entry)
    save_set(SENT_COMPLETE, sent_complete)

# ---------------------------------------------------------
# HOURLY SUMMARY
# ---------------------------------------------------------

def send_hourly_summary(yard):
    now = now_ist()
    if now.minute != 0:  # only at the top of the hour
        return

    start = now - timedelta(hours=1)
    end = now

    msg = f"📊 HOURLY SUMMARY ({start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')})\n\n"

    found = False

    for rst, d in yard.items():
        times = [t for t in [d["GrossTime"], d["TareTime"]] if t]

        if not times:
            continue

        tmax = max(times)

        if start <= tmax <= end:
            found = True
            net = abs((d["Gross"] or 0) - (d["Tare"] or 0))

            msg += (
                f"{rst} | {d['Vehicle']} | {d['Party']} | {d['Material']} | "
                f"IN {format_12h(min(times))} | OUT {format_12h(max(times))} | NET {net} Kg\n"
            )

    if not found:
        msg += "No weighments in this hour."

    send_telegram(msg)
    print("[HOURLY] Summary sent")

# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------

if __name__ == "__main__":
    while True:
        try:
            yard = scan_last_200_emails()

            sent_entry = load_set(SENT_ENTRY)
            sent_complete = load_set(SENT_COMPLETE)

            send_realtime_alerts(yard, sent_entry, sent_complete)
            send_hourly_summary(yard)

        except Exception as e:
            print("[ERR]", e)

        time.sleep(30)