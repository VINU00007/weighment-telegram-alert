import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
import json
from io import BytesIO
from datetime import datetime, timedelta
import pdfplumber

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"

PROCESSED_FILE = "processed.json"


# ================= TIME =================
def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def format_dt(dt_obj):
    if not dt_obj:
        return "Time Not Captured"
    return dt_obj.strftime("%d-%b-%y | %I:%M %p")


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
    if not dt_str:
        return None
    for fmt in ("%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(dt_str, fmt)
        except:
            pass
    return None


# ================= PDF EXTRACTION =================
def extract_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle No\s*:\s*([A-Z0-9\- ]+)"),
        "Material": normalize_text(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL")),
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

    # ENTRY-only
    if (tare_exists and not gross_exists) or (gross_exists and not tare_exists):
        in_type = "Tare" if tare_exists else "Gross"
        in_weight = info["TareKg"] if tare_exists else info["GrossKg"]
        in_time = tare_dt if tare_exists else gross_dt
        out_type = "Gross" if tare_exists else "Tare"

        msg = (
            "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
            f"🧾 RST : {rst}   🚛 {info['Vehicle']}\n"
            f"🌾 MATERIAL : {info['Material']}\n\n"
            f"⟪ IN  ⟫ {format_dt(in_time)}\n"
            f"⚖ {in_type} : {in_weight} Kg\n\n"
            "⟪ OUT ⟫ Pending final weighment\n"
            f"⚖ {out_type} : Pending\n\n"
            "🟡 STATUS : VEHICLE ENTERED YARD"
        )
        send_telegram(msg)
        return

    # COMPLETION
    if tare_exists and gross_exists and tare_dt and gross_dt:
        in_time = min(tare_dt, gross_dt)
        out_time = max(tare_dt, gross_dt)
        net = abs(int(info["GrossKg"]) - int(info["TareKg"]))

        msg = (
            "⚖️  WEIGHMENT ALERT  ⚖️\n\n"
            f"🧾 RST : {rst}   🚛 {info['Vehicle']}\n"
            f"🌾 MATERIAL : {info['Material']}\n\n"
            f"⟪ IN  ⟫ {format_dt(in_time)}\n"
            f"⟪ OUT ⟫ {format_dt(out_time)}\n\n"
            f"🔵 NET LOAD : {net} Kg\n\n"
            "▣ LOAD LOCKED & APPROVED FOR GATE PASS"
        )
        send_telegram(msg)


# ================= MAIL CHECK (BULLETPROOF) =================
def check_mail():
    # Load processed UIDs
    try:
        processed = set(json.load(open(PROCESSED_FILE)))
    except:
        processed = set()

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    # Always scan last 20 emails
    result, data = mail.uid("search", None, "ALL")
    all_uids = [int(x) for x in data[0].split()]
    recent_uids = all_uids[-20:]  # Bulletproof window

    for uid in recent_uids:
        if uid in processed:
            continue

        result, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = safe_decode(msg.get("Subject")).upper()

        # Detect weighment subject
        if not ("WEIGH" in subject or "SLIP" in subject):
            continue

        # Accept ANY PDF type
        for part in msg.walk():
            if "pdf" in part.get_content_type():
                pdf_bytes = part.get_payload(decode=True)
                if pdf_bytes:
                    try:
                        info = extract_from_pdf_bytes(pdf_bytes)
                        process_weighment(info)
                        processed.add(uid)
                    except Exception as e:
                        print("PDF ERROR:", e)

    # Save processed UIDs
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed), f)

    mail.logout()


# ================= MAIN LOOP =================
if __name__ == "__main__":
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", e)

        time.sleep(30)