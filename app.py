import imaplib
import email
import fitz
import re
import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CHAT_ID = None
LAST_EMAIL = None


# -------------------------
# PARSE PDF
# -------------------------
def parse_pdf(pdf_bytes):

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""

    for page in doc:
        text += page.get_text()

    def find(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    rst = find(r"RST\s*:\s*(\d+)")
    vehicle = find(r"Vehicle\s*No\s*:\s*([A-Z0-9]+)")
    party = find(r"PARTY\s*NAME\s*:\s*(.+)")
    place = find(r"PLACE\s*:\s*(.+)")
    material = find(r"MATERIAL\s*:\s*(.+)")

    gross = find(r"Gross\.\s*:\s*(\d+)")
    tare = find(r"Tare\.\s*:\s*(\d+)")
    net = find(r"Net\.\s*:\s*(\d+)")

    times = re.findall(
        r"\d{2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M", text
    )

    gross_time = times[0] if len(times) >= 1 else "-"
    tare_time = times[1] if len(times) >= 2 else "-"

    yard = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            t1 = datetime.strptime(gross_time, "%d-%b-%y %I:%M:%S %p")
            t2 = datetime.strptime(tare_time, "%d-%b-%y %I:%M:%S %p")

            diff = abs(t1 - t2)

            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60
            s = diff.seconds % 60

            yard = f"{h}h {m}m {s}s"

    except:
        pass

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time, yard


# -------------------------
# CHECK EMAIL
# -------------------------
def check_email():

    global LAST_EMAIL

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    result, data = mail.search(None, "ALL")
    ids = data[0].split()

    if not ids:
        return None

    latest_id = ids[-1]

    if LAST_EMAIL == latest_id:
        return None

    LAST_EMAIL = latest_id

    result, msg_data = mail.fetch(latest_id, "(RFC822)")
    msg = email.message_from_bytes(msg_data[0][1])

    for part in msg.walk():

        if part.get_content_type() == "application/pdf":

            pdf = part.get_payload(decode=True)
            return parse_pdf(pdf)

    return None


# -------------------------
# MONITOR LOOP
# -------------------------
async def monitor():

    while True:

        try:

            slip = check_email()

            if slip and CHAT_ID:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt, yard = slip

                msg = f"""
⚖️ WEIGHMENT SLIP

RST : {rst}
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

                await bot.send_message(CHAT_ID, msg)

        except Exception as e:
            print("ERROR:", e)

        await asyncio.sleep(30)


# -------------------------
# START COMMAND
# -------------------------
@dp.message(Command("start"))
async def start(msg: Message):

    global CHAT_ID
    CHAT_ID = msg.chat.id

    await msg.answer("✅ Weighment alert bot activated.")


# -------------------------
# MAIN
# -------------------------
async def main():

    asyncio.create_task(monitor())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())