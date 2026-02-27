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


def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def format_12h(dt):
    return dt.strftime("%I:%M %p")


def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass


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


def parse_dt(s):
    if not s:
        return None
    fmts = ["%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None


def load_set(file):
    if not os.path.exists(file):
        return set()
    try:
        return set(json.load(open(file)))
    except:
        return set()


def save_set(file, data):
    json.dump(list(data), open(file, "w"), indent=2)


def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        print("[ERR] PDF read failure")
        return {}

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)"),
        "Material": normalize(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL")),
        "GrossKg": pick(text, r"Gross\.?:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.?:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross.*?Kgs.*?" + dt_pat),
        "TareDT": pick(text, r"Tare.*?Kgs.*?" + dt_pat)
    }


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


def send_realtime_alerts(yard, sent_entry, sent_complete):
    for rst, d in yard.items():
        gross = d["Gross"]
        tare = d["Tare"]

        # ENTRY detection
        if (gross and not tare) or (tare and not gross):
            if rst not in sent_entry:
                in_time = d["GrossTime"] if gross else d["TareTime"]
                in_type = "Gross" if gross else "Tare"
                in_wt = gross if gross else tare

                text = (
                    f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                    f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']}\n"
                    f"IN {format_12h(in_time)} | {in_type}: {in_wt} Kg\n"
                    f"Pending {'Tare' if gross else 'Gross'}"
                )
                send_telegram(text)
                sent_entry.add(rst)
                print(f"[ENTRY] Alert sent for RST {rst}")

        # COMPLETION detection
        if gross and tare:
            if rst not in sent_complete:
                in_time = min(d["GrossTime"], d["TareTime"])
                out_time = max(d["GrossTime"], d["TareTime"])
                net = abs(gross - tare)

                text = (
                    f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                    f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']}\n"
                    f"IN {format_12h(in_time)} | OUT {format_12h(out_time)} | NET {net} Kg"
                )
                send_telegram(text)
                sent_complete.add(rst)
                print(f"[COMPLETE] Alert sent for RST {rst}")

    save_set(SENT_ENTRY, sent_entry)
    save_set(SENT_COMPLETE, sent_complete)


def recover_missed_alerts(yard, sent_complete):
    for rst, d in yard.items():
        if d["Gross"] and d["Tare"]:
            if rst not in sent_complete:
                in_time = min(d["GrossTime"], d["TareTime"])
                out_time = max(d["GrossTime"], d["TareTime"])
                net = abs(d["Gross"] - d["Tare"])

                msg = (
                    f"⚠️ MISSED ALERT RECOVERED ⚠️\n\n"
                    f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']}\n"
                    f"IN {format_12h(in_time)} | OUT {format_12h(out_time)} | NET {net} Kg"
                )
                send_telegram(msg)
                sent_complete.add(rst)
                print(f"[RECOVERY] Completion recovered for RST {rst}")

    save_set(SENT_COMPLETE, sent_complete)


def send_daily_summary(yard):
    now = now_ist()
    if now.hour != 10 or now.minute != 0:
        return

    start = (now - timedelta(days=1)).replace(hour=10, minute=0, second=0)
    end = now.replace(hour=10, minute=0, second=0)

    msg = f"📊 TODAY’S SUMMARY ({now.strftime('%d-%b %I:%M %p')})\n\n"

    # Completed first
    for rst, d in yard.items():
        if d["Gross"] and d["Tare"]:
            out_time = max(d["GrossTime"], d["TareTime"])
            if not (start <= out_time <= end):
                continue

            in_time = min(d["GrossTime"], d["TareTime"])
            net = abs(d["Gross"] - d["Tare"])

            msg += (
                f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']} | "
                f"IN {format_12h(in_time)} | OUT {format_12h(out_time)} | NET {net} Kg\n"
            )

    # Pending second
    for rst, d in yard.items():
        if (d["Gross"] and not d["Tare"]) or (d["Tare"] and not d["Gross"]):
            in_time = d["GrossTime"] if d["Gross"] else d["TareTime"]
            pending = "Tare" if d["Gross"] else "Gross"

            msg += (
                f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']} | "
                f"IN {format_12h(in_time)} | Pending {pending}\n"
            )

    send_telegram(msg)
    print("[SUMMARY] Daily summary sent")


if __name__ == "__main__":
    while True:
        try:
            yard = scan_last_50_emails()

            sent_entry = load_set(SENT_ENTRY)
            sent_complete = load_set(SENT_COMPLETE)

            send_realtime_alerts(yard, sent_entry, sent_complete)
            recover_missed_alerts(yard, sent_complete)
            send_daily_summary(yard)

        except Exception as e:
            print("[ERR]", e)

        time.sleep(30)