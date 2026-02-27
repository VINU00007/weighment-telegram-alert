import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
from datetime import datetime, timedelta
from io import BytesIO
import pdfplumber

IMAP_SERVER = "imap.gmail.com"

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


# ---------------- TIME ---------------- #

def format_12h(dt):
    if not dt:
        return "Time N/A"
    return dt.strftime("%I:%M %p")


def parse_datetime(date_str, time_str):
    try:
        combined = f"{date_str} {time_str}"
        return datetime.strptime(combined, "%d-%b-%y %I:%M:%S %p")
    except:
        return None


# ---------------- TELEGRAM ---------------- #

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("[ERR] Telegram send failed:", e)


# ---------------- HELPERS ---------------- #

def safe_decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def pick(text, pattern):
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


# ---------------- PDF EXTRACTION (FINAL FIXED) ---------------- #

def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        print("[ERR] PDF read failure")
        return {}

    # Extract weights
    gross_match = re.search(r"Gross\.\s*:\s*(\d+)\s*Kgs\s+(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s+[AP]M)", text)
    tare_match  = re.search(r"Tare\.\s*:\s*(\d+)\s*Kgs\s+(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s+[AP]M)", text)

    gross_val = None
    gross_dt = None
    tare_val = None
    tare_dt = None

    if gross_match:
        gross_val = int(gross_match.group(1))
        gross_dt = parse_datetime(gross_match.group(2), gross_match.group(3))

    if tare_match:
        tare_val = int(tare_match.group(1))
        tare_dt = parse_datetime(tare_match.group(2), tare_match.group(3))

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\-]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 ]+)"),
        "Material": pick(text, r"MATERIAL\s*:\s*([A-Za-z0-9 ]+)"),
        "Gross": gross_val,
        "GrossTime": gross_dt,
        "Tare": tare_val,
        "TareTime": tare_dt
    }


# ---------------- EMAIL SCAN ---------------- #

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

                yard[info["RST"]] = info

    mail.logout()
    print(f"[SCAN] {len(yard)} RST entries built")
    return yard


# ---------------- ALERT SENDER ---------------- #

def send_all_alerts(yard):
    for rst, d in yard.items():

        gross = d["Gross"]
        tare = d["Tare"]

        if gross and tare:
            in_time = min(d["GrossTime"], d["TareTime"])
            out_time = max(d["GrossTime"], d["TareTime"])
            net = abs(gross - tare)

            msg = (
                f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']}\n"
                f"IN {format_12h(in_time)} | OUT {format_12h(out_time)} | NET {net} Kg"
            )

            send_telegram(msg)
            print(f"[COMPLETE] Sent RST {rst}")

        elif gross or tare:
            in_time = d["GrossTime"] if gross else d["TareTime"]
            in_type = "Gross" if gross else "Tare"
            in_wt = gross if gross else tare

            msg = (
                f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                f"RST {rst} | {d['Vehicle']} | {d['Party']} | {d['Material']}\n"
                f"IN {format_12h(in_time)} | {in_type}: {in_wt} Kg\n"
                f"Pending {'Tare' if gross else 'Gross'}"
            )

            send_telegram(msg)
            print(f"[ENTRY] Sent RST {rst}")


# ---------------- MAIN LOOP ---------------- #

if __name__ == "__main__":
    while True:
        try:
            yard = scan_last_50_emails()
            send_all_alerts(yard)
        except Exception as e:
            print("[ERR]", e)

        time.sleep(30)