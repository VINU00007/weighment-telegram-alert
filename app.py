import os
import asyncio
import imaplib
import email
import re
import fitz
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

IMAP_SERVER = "imap.gmail.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# -------------------------
# READ PDF
# -------------------------
def read_pdf(data):

    text = ""

    pdf = fitz.open(stream=data, filetype="pdf")

    for page in pdf:
        text += page.get_text()

    return text


# -------------------------
# PARSE WEIGHMENT DATA
# -------------------------
def parse_data(text):

    data = {}

    def find(pattern):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else "-"

    data["rst"] = find(r"RST\s*:\s*(\d+)")
    data["vehicle"] = find(r"Vehicle No\s*:\s*([A-Z0-9]+)")
    data["party"] = find(r"PARTY NAME\s*:\s*([A-Z ]+)")
    data["place"] = find(r"PLACE\s*:\s*([A-Z]+)")
    data["material"] = find(r"MATERIAL\s*:\s*([A-Z ]+)")
    data["gross"] = find(r"Gross\.\s*:\s*(\d+)")
    data["tare"] = find(r"Tare\.\s*:\s*(\d+)")
    data["net"] = find(r"Net\.\s*:\s*(\d+)")
    data["date"] = find(r"(\d{2}-[A-Za-z]{3}-\d{2})")
    data["time"] = find(r"\d{1,2}:\d{2}:\d{2}\s*[AP]M")

    return data


# -------------------------
# FETCH EMAILS
# -------------------------
def fetch_slips():

    slips = []

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, 'SUBJECT "WEIGHMENT"')

    mail_ids = messages[0].split()

    for num in mail_ids[-50:]:

        status, msg_data = mail.fetch(num, "(RFC822)")

        for part in msg_data:

            if isinstance(part, tuple):

                msg = email.message_from_bytes(part[1])

                for p in msg.walk():

                    if p.get_content_type() == "application/pdf":

                        pdf_data = p.get_payload(decode=True)

                        text = read_pdf(pdf_data)

                        slips.append(parse_data(text))

    return slips


# -------------------------
# TELEGRAM COMMAND
# -------------------------
@dp.message(CommandStart())
async def start(message: Message):

    slips = fetch_slips()

    if len(slips) == 0:
        await message.answer("⚠ No weighment slips found.")
        return

    msg = "📥 Latest Weighment Slips\n\n"

    for s in slips:

        msg += (
            f"RST: {s['rst']}\n"
            f"🚛 Vehicle: {s['vehicle']}\n"
            f"🏢 Party: {s['party']}\n"
            f"📍 Place: {s['place']}\n"
            f"🌾 Material: {s['material']}\n"
            f"⚖ Gross: {s['gross']} | Tare: {s['tare']} | Net: {s['net']}\n"
            f"🕒 {s['date']} {s['time']}\n\n"
        )

    await message.answer(msg)


# -------------------------
# RUN BOT
# -------------------------
async def main():

    print("BOT RUNNING — WEIGHMENT PARSER ACTIVE")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())