import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
from io import BytesIO
from datetime import datetime

import pdfplumber

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"
KEYWORDS = ["WEIGHMENT"]


def send_telegram(message: str):
    if len(message) > 3800:
        message = message[:3800] + "\n\n...(truncated)"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()


def safe_decode(value):
    if not value:
        return ""
    try:
        parts = decode_header(value)
        out = []
        for part, enc in parts:
            if isinstance(part, bytes):
                out.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(part))
        return "".join(out)
    except Exception:
        return str(value)


def pick(text: str, pattern: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def parse_dt(dt_str):
    try:
        return datetime.strptime(dt_str, "%d-%b-%y %I:%M:%S %p")
    except:
        try:
            return datetime.strptime(dt_str, "%d-%b-%Y %I:%M:%S %p")
        except:
            return None


def format_dt(dt_str):
    dt_obj = parse_dt(dt_str)
    if not dt_obj:
        return dt_str
    return dt_obj.strftime("%d-%b-%y | %I:%M %p")


def extract_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""

    rst = pick(text, r"RST\s*:\s*(\d+)")
    vehicle = pick(text, r"Vehicle No\s*:\s*([A-Z0-9\- ]+)")
    party = pick(text, r"PARTY NAME:\s*(.+?)\s+PLACE")
    place = pick(text, r"PLACE\s*:\s*([A-Z0-9\- ]+)")
    material = normalize_text(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL NO"))
    bags = pick(text, r"\bBAGS\b\.?\s*:\s*(\d+)")

    gross = pick(text, r"Gross\.\s*:\s*(\d+)")
    tare = pick(text, r"Tare\.\s*:\s*(\d+)")
    net = pick(text, r"Net\.\s*:\s*(\d+)")

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    gross_dt = pick(text, r"Gross\.\s*:\s*\d+\s*Kgs\s*" + dt_pat)
    tare_dt = pick(text, r"Tare\.\s*:\s*\d+\s*Kgs\s*" + dt_pat)

    return {
        "RST": rst,
        "Vehicle": vehicle,
        "Party": normalize_text(party),
        "Place": normalize_text(place),
        "Material": material,
        "Bags": bags,
        "GrossKg": gross,
        "GrossDT": gross_dt,
        "TareKg": tare,
        "TareDT": tare_dt,
        "NetKg": net,
    }


def check_mail():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, "(UNSEEN)")
    mail_ids = messages[0].split()

    for mail_id in mail_ids:
        status, msg_data = mail.fetch(mail_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = safe_decode(msg.get("Subject"))

        if not any(k in subject.upper() for k in KEYWORDS):
            mail.store(mail_id, "+FLAGS", "\\Seen")
            continue

        pdfs = []

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue

                filename = part.get_filename()
                content_type = (part.get_content_type() or "").lower()
                filename_dec = safe_decode(filename) if filename else ""

                if filename_dec.lower().endswith(".pdf") or content_type == "application/pdf":
                    data = part.get_payload(decode=True)
                    if data:
                        pdfs.append((filename_dec or "weighment.pdf", data))

        if not pdfs:
            mail.store(mail_id, "+FLAGS", "\\Seen")
            continue

        for fname, data in pdfs:
            try:
                info = extract_from_pdf_bytes(data)
            except Exception as e:
                send_telegram(f"PDF Parse Error\n{fname}\n{e}")
                continue

            gross_dt_obj = parse_dt(info.get("GrossDT", ""))
            tare_dt_obj = parse_dt(info.get("TareDT", ""))

            duration_text = "N/A"
            if gross_dt_obj and tare_dt_obj:
                diff = gross_dt_obj - tare_dt_obj
                total_minutes = int(diff.total_seconds() // 60)
                hours = total_minutes // 60
                minutes = total_minutes % 60
                duration_text = f"{hours}h {minutes}m"

            msg_text = (
                "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
                f"🧾 SLIP : {info.get('RST','')}   🚛 {info.get('Vehicle','')}\n"
                f"👤 {info.get('Party','')}\n"
                f"📍 PLACE : {info.get('Place','')}\n"
                f"🌾 MATERIAL : {info.get('Material','')}\n"
                f"📦 BAGS : {info.get('Bags','')}\n\n"
                "────────────────────\n"
                f"⟪ IN  ⟫ {format_dt(info.get('TareDT',''))}\n"
                f"⚖ Tare  : {info.get('TareKg','')} Kg\n"
                f"⟪ OUT ⟫ {format_dt(info.get('GrossDT',''))}\n"
                f"⚖ Gross : {info.get('GrossKg','')} Kg\n"
                "────────────────────\n"
                f"🔵 NET LOAD : {info.get('NetKg','')} Kg\n"
                f"🟡 YARD TIME : {duration_text}\n"
                "▣ ENTRY LOGGED\n"
                "▣ LOAD SEALED & CLOSED"
            )

            send_telegram(msg_text)

        mail.store(mail_id, "+FLAGS", "\\Seen")

    mail.logout()


if __name__ == "__main__":
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", e)
        time.sleep(30)
