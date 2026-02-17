import imaplib
import email
from email.header import decode_header
import os
import requests
import time

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"


def send_telegram(message: str):
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


def check_mail():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    # Only unseen mails. You can add filters later.
    status, messages = mail.search(None, "(UNSEEN)")
    mail_ids = messages[0].split()

    for mail_id in mail_ids:
        status, msg_data = mail.fetch(mail_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = safe_decode(msg.get("Subject"))
        from_email = safe_decode(msg.get("From"))

        # Optional: only alert for weighment-related mails
        # Adjust keywords as needed
        subject_u = subject.upper()
        if "WEIGHMENT" not in subject_u and "WEIGHMENT SLIP" not in subject_u:
            # mark as seen so it doesn't keep looping on unrelated mails
            mail.store(mail_id, "+FLAGS", "\\Seen")
            continue

        send_telegram(
            f"📩 Weighment Mail Received\n\nFrom: {from_email}\nSubject: {subject}"
        )

        mail.store(mail_id, "+FLAGS", "\\Seen")

    mail.logout()


if __name__ == "__main__":
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", e)
        time.sleep(30)
