import imaplib
import email
import pdfplumber
import re
import os
import asyncio
import io
from datetime import datetime
from aiogram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=BOT_TOKEN)

sent_events = set()


def parse_pdf(pdf_bytes):

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:

        text = ""

        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"

    text = re.sub(r"\s+", " ", text)

    def find(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    rst = find(r"RST\s*:\s*(\d+)")
    vehicle = find(r"Vehicle\s*No\s*:\s*([A-Z0-9]+)")
    party = find(r"PARTY\s*NAME\s*:\s*(.*?) PLACE")
    place = find(r"PLACE\s*:\s*([A-Z]+)")
    material = find(r"MATERIAL\s*:\s*(.*?) CELL")

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
        gross_time = f"{gross_match.group(2)} {gross_match.group(3)}"

    if tare_match:
        tare = tare_match.group(1)
        tare_time = f"{tare_match.group(2)} {tare_match.group(3)}"

    yard_time = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            g = datetime.strptime(gross_time, "%d-%b-%y %I:%M:%S %p")
            t = datetime.strptime(tare_time, "%d-%b-%y %I:%M:%S %p")

            diff = abs(g - t)

            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60

            yard_time = f"{h}h {m}m"

    except:
        pass

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time, yard_time


def check_mail():

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    result, data = mail.uid("search", None, "ALL")

    ids = data[0].split()[-10:]

    slips = []

    for uid in ids:

        result, msg_data = mail.uid("fetch", uid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        for part in msg.walk():

            if part.get_content_type() == "application/pdf":

                pdf_bytes = part.get_payload(decode=True)

                slips.append(parse_pdf(pdf_bytes))

    mail.logout()

    return slips


async def monitor():

    while True:

        try:

            slips = check_mail()

            for data in slips:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt, yard = data

                event_id = f"{rst}_{net}"

                if event_id in sent_events:
                    continue

                sent_events.add(event_id)

                if net != "-":

                    status = "🟢 STATUS : VEHICLE APPROVED FOR GATE PASS"
                    yard_status = f"⏱ Yard Time : {yard}"

                else:

                    status = "🟡 STATUS : SECOND WEIGHMENT PENDING"
                    yard_status = "⏱ Yard Status : VEHICLE IN YARD"

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

{yard_status}
{status}
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