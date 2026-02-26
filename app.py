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

pending_yard = {}
last_uid_processed = None


# ================= TELEGRAM =================
def send_telegram(message: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        requests.post(url, data=payload, timeout=20)
    except Exception as e:
        print("Telegram Error:", e)


# ================= HELPERS =================
def safe_decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


def pick(text: str, pattern: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_dt(dt_str):
    if not dt_str:
        return None
    for fmt in ("%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(dt_str, fmt)
        except:
            continue
    return None


def format_dt(dt_obj):
    if not dt_obj:
        return "Time Not Captured"
    return dt_obj.strftime("%d-%b-%y | %I:%M %p")


# ================= PDF EXTRACTION =================
def extract_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": normalize_text(pick(text, r"PARTY NAME:\s*(.+?)\s+PLACE")),
        "Place": normalize_text(pick(text, r"PLACE\s*:\s*([A-Z0-9\- ]+)")),
        "Material": normalize_text(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL NO")),
        "Bags": pick(text, r"\bBAGS\b\.?\s*:\s*(\d+)"),
        "GrossKg": pick(text, r"Gross\.\s*:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.\s*:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
        "TareDT": pick(text, r"Tare\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
    }


# ================= PROCESS WEIGHMENT =================
def process_weighment(info):
    rst = info["RST"]
    if not rst:
        return

    tare_exists = bool(info["TareKg"])
    gross_exists = bool(info["GrossKg"])

    tare_dt = parse_dt(info["TareDT"])
    gross_dt = parse_dt(info["GrossDT"])

    # ENTRY
    if (tare_exists and not gross_exists) or (gross_exists and not tare_exists):

        in_type = "Tare" if tare_exists else "Gross"
        in_weight = info["TareKg"] if tare_exists else info["GrossKg"]
        in_time = tare_dt if tare_exists else gross_dt
        out_type = "Gross" if tare_exists else "Tare"

        pending_yard[rst] = {
            "Vehicle": info["Vehicle"],
            "Material": info["Material"]
        }

        message = (
            "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
            f"🧾 RST : {rst}   🚛 {info['Vehicle']}\n"
            f"👤 PARTY : {info['Party']}\n"
            f"📍 PLACE : {info['Place']}\n"
            f"🌾 MATERIAL : {info['Material']}\n"
            f"📦 BAGS : {info['Bags'] or '-'}\n\n"
            f"⟪ IN  ⟫ {format_dt(in_time)}\n"
            f"⚖ {in_type}  : {in_weight} Kg\n\n"
            f"⟪ OUT ⟫ Pending final weighment\n"
            f"⚖ {out_type}  : Pending final weighment\n\n"
            "🟡 STATUS : VEHICLE ENTERED YARD"
        )
        send_telegram(message)
        return

    # COMPLETION
    if tare_exists and gross_exists and tare_dt and gross_dt:

        in_time = min(tare_dt, gross_dt)
        out_time = max(tare_dt, gross_dt)
        net = abs(int(info["GrossKg"]) - int(info["TareKg"]))
        duration = out_time - in_time
        minutes = int(duration.total_seconds() // 60)
        yard_time = f"{minutes // 60}h {minutes % 60}m"

        if rst in pending_yard:
            del pending_yard[rst]

        message = (
            "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
            f"🧾 RST : {rst}   🚛 {info['Vehicle']}\n"
            f"👤 PARTY : {info['Party']}\n"
            f"📍 PLACE : {info['Place']}\n"
            f"🌾 MATERIAL : {info['Material']}\n"
            f"📦 BAGS : {info['Bags'] or '-'}\n\n"
            f"⟪ IN  ⟫ {format_dt(in_time)}\n"
            f"⚖ Tare  : {info['TareKg']} Kg\n\n"
            f"⟪ OUT ⟫ {format_dt(out_time)}\n"
            f"⚖ Gross : {info['GrossKg']} Kg\n\n"
            f"🔵 NET LOAD : {net} Kg\n"
            f"🟡 YARD TIME : {yard_time}\n\n"
            "▣ LOAD LOCKED & APPROVED FOR GATE PASS"
        )
        send_telegram(message)


# ================= CHECK MAIL (UID BASED) =================
def check_mail():
    global last_uid_processed

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    result, data = mail.uid("search", None, "ALL")
    uids = data[0].split()

    if not uids:
        mail.logout()
        return

    if last_uid_processed is None:
        last_uid_processed = uids[-1]
        mail.logout()
        return

    new_uids = [uid for uid in uids if int(uid) > int(last_uid_processed)]

    for uid in new_uids:
        result, msg_data = mail.uid("fetch", uid, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        raw_subject = msg.get("Subject")
        subject = safe_decode(raw_subject) if raw_subject else ""

        if not any(k in subject.upper() for k in KEYWORDS):
            last_uid_processed = uid
            continue

        for part in msg.walk():
            if part.get_content_type() == "application/pdf":
                data = part.get_payload(decode=True)
                if data:
                    info = extract_from_pdf_bytes(data)
                    process_weighment(info)

        last_uid_processed = uid

    mail.logout()


# ================= MAIN =================
if __name__ == "__main__":
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Main Error:", e)

        time.sleep(30)