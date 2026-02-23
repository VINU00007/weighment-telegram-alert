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

completed_weighments = []
last_hour_sent = None


# ================= TIME (IST) =================
def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


# ================= TELEGRAM =================
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=payload, timeout=20)


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


def format_dt(dt_obj):
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


# ================= MAIN WEIGHMENT LOGIC =================
def process_weighment(info):

    tare_exists = bool(info["TareKg"])
    gross_exists = bool(info["GrossKg"])

    tare_dt = parse_dt(info["TareDT"]) if info["TareDT"] else None
    gross_dt = parse_dt(info["GrossDT"]) if info["GrossDT"] else None

    # ---------- ENTRY STAGE ----------
    if tare_exists and not gross_exists:
        in_type = "Tare"
        in_weight = info["TareKg"]
        in_time = tare_dt
        out_type = "Gross"

        message = build_entry_message(info, in_type, in_weight, in_time, out_type)
        send_telegram(message)
        return

    if gross_exists and not tare_exists:
        in_type = "Gross"
        in_weight = info["GrossKg"]
        in_time = gross_dt
        out_type = "Tare"

        message = build_entry_message(info, in_type, in_weight, in_time, out_type)
        send_telegram(message)
        return

    # ---------- COMPLETION STAGE ----------
    if tare_exists and gross_exists and tare_dt and gross_dt:

        if tare_dt < gross_dt:
            in_type = "Tare"
            in_weight = info["TareKg"]
            in_time = tare_dt

            out_type = "Gross"
            out_weight = info["GrossKg"]
            out_time = gross_dt
        else:
            in_type = "Gross"
            in_weight = info["GrossKg"]
            in_time = gross_dt

            out_type = "Tare"
            out_weight = info["TareKg"]
            out_time = tare_dt

        net = abs(int(info["GrossKg"]) - int(info["TareKg"]))
        duration = out_time - in_time
        minutes = int(duration.total_seconds() // 60)
        yard_time = f"{minutes // 60}h {minutes % 60}m"

        completed_weighments.append({
            "time": out_time,
            "net": net,
            "material": info["Material"]
        })

        message = build_completion_message(
            info,
            in_type, in_weight, in_time,
            out_type, out_weight, out_time,
            net, yard_time
        )

        send_telegram(message)


# ================= MESSAGE BUILDERS =================
def build_entry_message(info, in_type, in_weight, in_time, out_type):

    return (
        "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
        f"🧾 RST : {info['RST']}   🚛 {info['Vehicle']}\n"
        f"👤 {info['Party']}\n"
        f"📍 PLACE : {info['Place']}\n"
        f"🌾 MATERIAL : {info['Material']}\n"
        f"📦 BAGS : {info['Bags'] or '-'}\n\n"
        f"⟪ IN  ⟫ {format_dt(in_time)}\n"
        f"⚖ {in_type}  : {in_weight} Kg\n\n"
        f"⟪ OUT ⟫ Pending final weighment\n"
        f"⚖ {out_type}  : Pending final weighment\n\n"
        "🔵 NET LOAD : Pending final weighment\n"
        "🟡 YARD TIME : Pending final weighment\n\n"
        "🟡 STATUS : VEHICLE ENTERED YARD"
    )


def build_completion_message(info,
                             in_type, in_weight, in_time,
                             out_type, out_weight, out_time,
                             net, yard_time):

    return (
        "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
        f"🧾 RST : {info['RST']}   🚛 {info['Vehicle']}\n"
        f"👤 {info['Party']}\n"
        f"📍 PLACE : {info['Place']}\n"
        f"🌾 MATERIAL : {info['Material']}\n"
        f"📦 BAGS : {info['Bags'] or '-'}\n\n"
        f"⟪ IN  ⟫ {format_dt(in_time)}\n"
        f"⚖ {in_type}  : {in_weight} Kg\n\n"
        f"⟪ OUT ⟫ {format_dt(out_time)}\n"
        f"⚖ {out_type}  : {out_weight} Kg\n\n"
        f"🔵 NET LOAD : {net} Kg\n"
        f"🟡 YARD TIME : {yard_time}\n\n"
        "▣ LOAD LOCKED & APPROVED FOR GATE PASS"
    )


# ================= HOURLY STATUS =================
def send_hourly_status():
    global last_hour_sent

    now = now_ist()
    one_hour_ago = now - timedelta(hours=1)
    hour_label = now.strftime("%I %p").lstrip("0")

    recent = [w for w in completed_weighments if one_hour_ago <= w["time"] <= now]

    if not recent:
        message = (
            f"⏱ HOURLY STATUS – {hour_label}\n\n"
            "No Weighments Completed In The Past Hour."
        )
    else:
        total_net = sum(w["net"] for w in recent)
        message = (
            f"⏱ HOURLY STATUS – {hour_label}\n\n"
            f"Weighments Completed : {len(recent)}\n"
            f"Total Net This Hour  : {total_net:,} Kg"
        )

    send_telegram(message)
    last_hour_sent = now.strftime("%Y-%m-%d %H")


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
            if part.get_content_type() == "application/pdf":
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
            now = now_ist()
            hour_marker = now.strftime("%Y-%m-%d %H")

            if now.minute == 0 and hour_marker != last_hour_sent:
                send_hourly_status()

            check_mail()

        except Exception as e:
            print("Error:", e)

        time.sleep(30)