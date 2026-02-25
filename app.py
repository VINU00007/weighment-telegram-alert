import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
from io import BytesIO
from datetime import datetime, timedelta
import pdfplumber

# ================= CONFIG =================
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
KEYWORDS = ["WEIGHMENT"]

# ================= TELEGRAM =================
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=payload, timeout=20)


# ================= HELPERS =================
def safe_str(val):
    return str(val) if val else ""

def safe_pick(text, pattern):
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""

def parse_dt(dt_str):
    if not dt_str:
        return None
    for fmt in ("%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(dt_str, fmt)
        except:
            continue
    return None

def format_dt(dt_str):
    dt_obj = parse_dt(dt_str)
    return dt_obj.strftime("%d-%b-%y | %I:%M %p") if dt_obj else ""


# ================= PDF EXTRACTION =================
def extract_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        raw_text = pdf.pages[0].extract_text()
        text = raw_text if raw_text else ""

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    return {
        "RST": safe_pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": safe_pick(text, r"Vehicle No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": safe_pick(text, r"PARTY NAME:\s*(.+?)\s+PLACE"),
        "Place": safe_pick(text, r"PLACE\s*:\s*([A-Z0-9\- ]+)"),
        "Material": safe_pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL NO"),
        "Bags": safe_pick(text, r"\bBAGS\b\.?\s*:\s*(\d+)"),
        "GrossKg": safe_pick(text, r"Gross\.\s*:\s*(\d+)"),
        "TareKg": safe_pick(text, r"Tare\.\s*:\s*(\d+)"),
        "NetKg": safe_pick(text, r"Net\.\s*:\s*(\d+)"),
        "GrossDT": safe_pick(text, r"Gross\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
        "TareDT": safe_pick(text, r"Tare\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
    }


# ================= ENTRY ALERT =================
def send_entry_alert(info):
    message = (
        "⚖️  WEIGHMENT ENTRY  ⚖️\n\n"
        f"🧾 RST : {safe_str(info['RST'])}   🚛 {safe_str(info['Vehicle'])}\n"
        f"👤 {safe_str(info['Party'])}\n"
        f"📍 PLACE : {safe_str(info['Place'])}\n"
        f"🌾 MATERIAL : {safe_str(info['Material'])}\n"
        f"📦 BAGS : {safe_str(info['Bags'])}\n\n"
        f"🕒 Tare Time   : {format_dt(info['TareDT'])}\n"
        f"⚖ Tare Weight : {safe_str(info['TareKg'])} Kg\n\n"
        f"🕒 Gross Time  : {format_dt(info['GrossDT'])}\n"
        f"⚖ Gross Weight: {safe_str(info['GrossKg'])} Kg\n\n"
        f"🔵 NET LOAD     : {safe_str(info['NetKg'])} Kg\n\n"
        "🟡 STATUS : VEHICLE ENTERED YARD"
    )

    send_telegram(message)


# ================= COMPLETION ALERT =================
def send_completion_alert(info):
    net_val = safe_str(info["NetKg"]).replace(",", "")
    net_kg = int(net_val) if net_val.isdigit() else 0

    tare_dt_obj = parse_dt(info["TareDT"])
    gross_dt_obj = parse_dt(info["GrossDT"])

    duration_text = ""
    if tare_dt_obj and gross_dt_obj:
        diff = gross_dt_obj - tare_dt_obj
        mins = int(diff.total_seconds() // 60)
        duration_text = f"{mins // 60}h {mins % 60}m"

    message = (
        "⚖️  WEIGHMENT COMPLETED  ⚖️\n\n"
        f"🧾 RST : {safe_str(info['RST'])}   🚛 {safe_str(info['Vehicle'])}\n"
        f"👤 {safe_str(info['Party'])}\n"
        f"📍 PLACE : {safe_str(info['Place'])}\n"
        f"🌾 MATERIAL : {safe_str(info['Material'])}\n"
        f"📦 BAGS : {safe_str(info['Bags'])}\n\n"
        f"🕒 Tare Time   : {format_dt(info['TareDT'])}\n"
        f"⚖ Tare Weight : {safe_str(info['TareKg'])} Kg\n\n"
        f"🕒 Gross Time  : {format_dt(info['GrossDT'])}\n"
        f"⚖ Gross Weight: {safe_str(info['GrossKg'])} Kg\n\n"
        f"🔵 NET LOAD     : {net_kg} Kg\n"
        f"🟡 YARD TIME    : {duration_text}\n\n"
        "▣ LOAD LOCKED & APPROVED FOR GATE PASS"
    )

    send_telegram(message)


# ================= EMAIL CHECK =================
def check_mail():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, "(UNSEEN)")
    mail_ids = messages[0].split()

    for mail_id in mail_ids:
        status, msg_data = mail.fetch(mail_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg.get("Subject", "")
        if not any(k in subject.upper() for k in KEYWORDS):
            mail.store(mail_id, "+FLAGS", "\\Seen")
            continue

        for part in msg.walk():
            if part.get_content_type() == "application/pdf":
                data = part.get_payload(decode=True)
                if data:
                    info = extract_from_pdf_bytes(data)

                    if info["GrossKg"]:
                        send_completion_alert(info)
                    else:
                        send_entry_alert(info)

        mail.store(mail_id, "+FLAGS", "\\Seen")

    mail.logout()


# ================= MAIN LOOP =================
if __name__ == "__main__":
    print("🚀 Weighment Telegram Automation Started...")
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", e)

        time.sleep(30)