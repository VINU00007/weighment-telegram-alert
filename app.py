import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
from io import BytesIO

import pdfplumber

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"

# Optional filters (keep these loose)
KEYWORDS = ["WEIGHMENT", "WEIGHMENT SLIP"]


def send_telegram(message: str):
    # Telegram message limit safety
    if len(message) > 3800:
        message = message[:3800] + "\n\n…(truncated)"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()


def safe_decode(value):
    """Decode MIME encoded-words safely. Returns string (never None)."""
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


def normalize_material(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def extract_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = (pdf.pages[0].extract_text() or "")

    rst = pick(text, r"RST\s*:\s*(\d+)")
    vehicle = pick(text, r"Vehicle No\s*:\s*([A-Z0-9\- ]+)")
    party = pick(text, r"PARTY NAME:\s*(.+?)\s+PLACE")
    place = pick(text, r"PLACE\s*:\s*([A-Z0-9\- ]+)")
    material = normalize_material(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL NO"))
    bags = pick(text, r"BAGS\s*:\s*(\d+)")

    gross = pick(text, r"Gross\.\s*:\s*(\d+)")
    tare = pick(text, r"Tare\.\s*:\s*(\d+)")
    net = pick(text, r"Net\.\s*:\s*(\d+)")

    # Date/time strings shown on slip lines
    gross_dt = pick(text, r"Gross\.\s*:\s*\d+\s*Kgs\s*(.+)")
    tare_dt = pick(text, r"Tare\.\s*:\s*\d+\s*Kgs\s*(.+)")

    # If Net line has date/time on your slip, try to capture it too
    net_dt = pick(text, r"Net\.\s*:\s*\d+\s*Kgs\s*(.+)")

    return {
        "RST": rst,
        "Vehicle": vehicle.strip(),
        "Party": normalize_material(party),
        "Place": place.strip(),
        "Material": material,
        "Bags": bags,
        "GrossKg": gross,
        "GrossDT": gross_dt.strip(),
        "TareKg": tare,
        "TareDT": tare_dt.strip(),
        "NetKg": net,
        "NetDT": net_dt.strip(),
    }


def mail_matches(subject: str, from_email: str) -> bool:
    s = (subject or "").upper()
    for k in KEYWORDS:
        if k in s:
            return True
    # if subject doesn't include keywords, still allow based on sender if you want
    # return "vtsbharat@gmail.com" in (from_email or "").lower()
    return False


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
        from_email = safe_decode(msg.get("From"))
        received_ts = msg.get("Date") or ""

        if not mail_matches(subject, from_email):
            mail.store(mail_id, "+FLAGS", "\\Seen")
            continue

        # Collect PDF attachments
        pdfs = []  # list of (filename, bytes)
        if msg.is_multipart():
            for part in msg.walk():
                disp = (part.get("Content-Disposition") or "")
                if "attachment" not in disp.lower():
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                filename_dec = safe_decode(filename)
                if filename_dec.lower().endswith(".pdf"):
                    data = part.get_payload(decode=True)
                    if data:
                        pdfs.append((filename_dec, data))
        else:
            # rare case: single-part attachment
            filename = msg.get_filename()
            if filename and safe_decode(filename).lower().endswith(".pdf"):
                data = msg.get_payload(decode=True)
                if data:
                    pdfs.append((safe_decode(filename), data))

        if not pdfs:
            # Still notify basic mail if needed
            send_telegram(
                "📩 Weighment Mail (no PDF found)\n\n"
                f"From: {from_email}\nDate: {received_ts}\nSubject: {subject}"
            )
            mail.store(mail_id, "+FLAGS", "\\Seen")
            continue

        # For each PDF, extract and send details
        for (fname, data) in pdfs:
            try:
                info = extract_from_pdf_bytes(data)
            except Exception as e:
                send_telegram(
                    "⚠️ Weighment PDF received but parse failed\n\n"
                    f"From: {from_email}\nDate: {received_ts}\nSubject: {subject}\n"
                    f"PDF: {fname}\nError: {e}"
                )
                continue

            msg_text = (
                "📄 Weighment Slip Details\n\n"
                f"RST No: {info.get('RST','')}\n"
                f"Vehicle: {info.get('Vehicle','')}\n"
                f"Party: {info.get('Party','')}\n"
                f"Place: {info.get('Place','')}\n"
                f"Material: {info.get('Material','')}\n"
                f"Bags: {info.get('Bags','')}\n\n"
                f"Gross (Kg): {info.get('GrossKg','')}  | Time: {info.get('GrossDT','')}\n"
                f"Tare  (Kg): {info.get('TareKg','')}  | Time: {info.get('TareDT','')}\n"
                f"Net   (Kg): {info.get('NetKg','')}  | Time: {info.get('NetDT','')}\n\n"
                f"Email Date: {received_ts}\n"
                f"PDF: {fname}"
            )
            send_telegram(msg_text)

        # Mark mail as seen after processing
        mail.store(mail_id, "+FLAGS", "\\Seen")

    mail.logout()


if __name__ == "__main__":
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", e)
        time.sleep(30)
