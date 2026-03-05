import imaplib
import email
import fitz
import re
import os
import asyncio
from datetime import datetime
from aiogram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=BOT_TOKEN)
LAST_UID = None


def parse_pdf(pdf_bytes):

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    text = ""
    for page in doc:
        text += page.get_text()

    text = re.sub(r"\s+", " ", text)

    def find(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    rst = find(r"RST\s*:\s*(\d+)")
    vehicle = find(r"Vehicle\s*No\s*:\s*([A-Z0-9]+)")
    party = find(r"PARTY\s*NAME\s*:? ([A-Z\s]+?) PLACE")
    place = find(r"PLACE\s*:\s*([A-Z]+)")
    material = find(r"MATERIAL\s*:\s*([A-Z\s]+?) CELL")

    gross_match = re.search(
        r"Gross\.\s*:\s*(\d+)\s*Kgs\s*(\d{2}-[A-Za-z]{3}-\d{2})\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        text,
    )

    tare_match = re.search(
        r"Tare\.\s*:\s*(\d+)\s*Kgs\s*(\d{2}-[A-Za-z]{3}-\d{2})\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        text,
    )

    net = find(r"Net\.\s*:\s*(\d+)")

    gross = "-"
    tare = "-"
    gross_time = "-"
    tare_time = "-"

    if gross_match:
        gross = gross_match.group(1)
        gross_time = gross_match.group(2) + " " + gross_match.group(3)

    if tare_match:
        tare = tare_match.group(1)
        tare_time = tare_match.group(2) + " " + tare_match.group(3)

    yard = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            g = datetime.strptime(gross_time, "%d-%b-%y %I:%M:%S %p")
            t = datetime.strptime(tare_time, "%d-%b-%y %I:%M:%S %p")

            diff = abs(g - t)

            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60
            s = diff.seconds % 60

            yard = f"{h}h {m}m {s}s"

    except:
        pass

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time, yard


def check_mail():

    global LAST_UID

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    result, data = mail.uid("search", None, "ALL")
    ids = data[0].split()

    if not ids:
        return None

    latest_uid = ids[-1]

    if latest_uid == LAST_UID:
        return None

    LAST_UID = latest_uid

    result, msg_data = mail.uid("fetch", latest_uid, "(RFC822)")
    msg = email.message_from_bytes(msg_data[0][1])

    for part in msg.walk():

        if part.get_content_type() == "application/pdf":

            pdf_bytes = part.get_payload(decode=True)

            return parse_pdf(pdf_bytes)

    return None


async def monitor():

    while True:

        try:

            data = check_mail()

            if data:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt, yard = data

                message = f"""
⚖️ WEIGHMENT ALERT

🧾 RST : {rst}
🚛 Vehicle : {vehicle}

🏢 Party : {party}
📍 Place : {place}
🌾 Material : {material}

⚖ Gross : {gross} Kg
🕒 {gt}

⚖ Tare : {tare} Kg
🕒 {tt}

📦 Net : {net} Kg

⏱ Yard Time : {yard}
"""

                await bot.send_message(CHAT_ID, message)

        except Exception as e:
            print("MAIL ERROR:", e)

        await asyncio.sleep(30)


async def main():

    await bot.delete_webhook(drop_pending_updates=True)

    print("BOT RUNNING — WEIGHMENT PARSER ACTIVE")

    await monitor()


if __name__ == "__main__":
    asyncio.run(main())