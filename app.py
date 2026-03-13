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

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"
KEYWORDS = ["WEIGHMENT"]

# ===== In-Memory Storage =====
vehicle_log = {}
completed_weighments = []


# ================= TIME (IST) =================
def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


# ================= TELEGRAM =================
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()


# ================= HELPERS =================
def safe_decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


def pick(text: str, pattern: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_dt(dt_str):
    for fmt in ("%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(dt_str, fmt)
        except:
            continue
    return None


def format_dt(dt_str):
    dt_obj = parse_dt(dt_str)
    return dt_obj.strftime("%d-%b-%y | %I:%M %p") if dt_obj else dt_str


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
        "NetKg": pick(text, r"Net\.\s*:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
        "TareDT": pick(text, r"Tare\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
    }


# ================= PROCESS WEIGHMENT =================
def process_weighment(info):
    global vehicle_log, completed_weighments

    today_key = now_ist().strftime("%Y-%m-%d")
    if today_key not in vehicle_log:
        vehicle_log[today_key] = set()

    vehicle = info["Vehicle"]
    net_kg = int(info["NetKg"] or 0)
    material = info["Material"]

    exit_dt_obj = parse_dt(info["GrossDT"])
    tare_dt_obj = parse_dt(info["TareDT"])

    duration_text = "N/A"
    if exit_dt_obj and tare_dt_obj:
        diff = exit_dt_obj - tare_dt_obj
        mins = int(diff.total_seconds() // 60)
        duration_text = f"{mins // 60}h {mins % 60}m"

    high_load_flag = "⬆ HIGH LOAD\n" if net_kg > 20000 else ""
    repeat_flag = "🔁 REPEAT VEHICLE\n" if vehicle in vehicle_log[today_key] else ""
    vehicle_log[today_key].add(vehicle)

    if exit_dt_obj:
        completed_weighments.append({
            "time": exit_dt_obj,
            "net": net_kg,
            "material": material,
            "high": net_kg > 20000
        })

    # ===== STATUS MESSAGE FIX =====
    status_text = "*▣ ENTRY LOGGED*"
    if net_kg > 0:
        status_text += "\n*▣ LOAD LOCKED & APPROVED FOR GATE PASS*"

    message = (
        "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
        f"🧾 RST : {info['RST']}   🚛 {vehicle}\n"
        f"👤 {info['Party']}\n"
        f"📍 PLACE : {info['Place']}\n"
        f"🌾 MATERIAL : {material}\n"
        f"📦 BAGS : {info['Bags']}\n\n"
        f"⟪ IN  ⟫ {format_dt(info['TareDT'])}\n"
        f"⚖ Tare  : {info['TareKg']} Kg\n"
        f"⟪ OUT ⟫ {format_dt(info['GrossDT'])}\n"
        f"⚖ Gross : {info['GrossKg']} Kg\n\n"
        f"🔵 NET LOAD : {net_kg} Kg\n"
        f"🟡 YARD TIME : {duration_text}\n"
        f"{high_load_flag}"
        f"{repeat_flag}\n"
        f"{status_text}"
    )

    send_telegram(message.strip())


# ================= EMAIL CHECK =================
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

        for part in msg.walk():
            filename = part.get_filename()
            content_type = part.get_content_type()

            if (
                (filename and filename.lower().endswith(".pdf"))
                or content_type == "application/pdf"
            ):
                data = part.get_payload(decode=True)
                if data:
                    info = extract_from_pdf_bytes(data)
                    process_weighment(info)

        mail.store(mail_id, "+FLAGS", "\\Seen")

    mail.logout()


# ================= MAIN LOOP =================
if __name__ == "__main__":
    while True:
        try:
            check_mail()

        except Exception as e:
            print("Error:", e)

        time.sleep(30)