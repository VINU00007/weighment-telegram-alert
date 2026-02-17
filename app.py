import imaplib
import email
import os
import requests
import time

# ====== CONFIG FROM ENV VARIABLES ======
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=payload)


def check_mail():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, '(UNSEEN)')
    mail_ids = messages[0].split()

    for mail_id in mail_ids:
        status, msg_data = mail.fetch(mail_id, '(RFC822)')
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        from_email = msg["from"]

        send_telegram(f"📩 New Mail Received\n\nFrom: {from_email}\nSubject: {subject}")

        mail.store(mail_id, '+FLAGS', '\\Seen')

    mail.logout()


if __name__ == "__main__":
    while True:
        try:
            check_mail()
        except Exception as e:
            print("Error:", e)
        time.sleep(30)
