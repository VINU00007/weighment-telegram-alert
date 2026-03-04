import imaplib
import email
import fitz
import re
import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CHAT_ID = None
last_uid = None


# -------------------------
# PDF PARSER
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

    times = re.findall(r"\d{2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M", text)

    gross_time = "-"
    tare_time = "-"

    if len(times) >= 1:
        gross_time = times[0]

    if len(times) >= 2:
        tare_time = times[1]

    yard_time = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            t1 = datetime.strptime(gross_time, "%d-%b-%y %I:%M:%S %p")
            t2 = datetime.strptime(tare_time, "%d-%b-%y %I:%M:%S %p")

            diff = abs(t1 - t2)

            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            seconds = diff.seconds % 60

            yard_time = f"{hours}h {minutes}m {seconds}s"

    except:
        pass

    return {
        "rst": rst,
        "vehicle": vehicle,
        "party": party,
        "place": place,
        "material": material,
        "gross": gross,
        "tare": tare,
        "net": net,
        "gross_time": gross_time,
        "tare_time": tare_time,
        "yard_time": yard_time
    }


# -------------------------
# EMAIL CHECKER
# -------------------------
def check_email():

    global last_uid

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    result, data = mail.uid("search", None, "ALL")
    ids = data[0].split()

    if not ids:
        return []

    if last_uid is None:
        last_uid = ids[-1]
        return []

    new_ids = [i for i in ids if int(i) > int(last_uid)]

    slips = []

    for uid in new_ids:

        result, msg_data = mail.uid("fetch", uid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        for part in msg.walk():

            if part.get_content_type() == "application/pdf":

                pdf_bytes = part.get_payload(decode=True)
                slip = parse_pdf(pdf_bytes)
                slips.append(slip)

        last_uid = uid

    mail.logout()

    return slips


# -------------------------
# MONITOR
# -------------------------
async def monitor():

    while True:

        slips = check_email()

        for s in slips:

            if CHAT_ID is None:
                continue

            msg = f"""
⚖️ WEIGHMENT SLIP

RST : {s['rst']}
🚛 Vehicle : {s['vehicle']}

🏢 Party : {s['party']}
📍 Place : {s['place']}
🌾 Material : {s['material']}

⚖ Gross : {s['gross']} Kg
🕒 {s['gross_time']}

⚖ Tare : {s['tare']} Kg
🕒 {s['tare_time']}

📦 Net : {s['net']} Kg

⏱ Yard Time : {s['yard_time']}
"""

            await bot.send_message(CHAT_ID, msg)

        await asyncio.sleep(20)


# -------------------------
# START
# -------------------------
@dp.message(Command("start"))
async def start(msg: types.Message):

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