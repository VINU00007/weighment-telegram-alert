import os
import asyncio
import imaplib
import email
import re
import fitz
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

# -------------------------
# ENV VARIABLES
# -------------------------

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
# SAFE FIND FUNCTION
# -------------------------

def find(pattern, text):

    m = re.search(pattern, text)

    if not m:
        return "-"

    if m.lastindex:
        return m.group(1).strip()

    return m.group(0).strip()


# -------------------------
# PARSE WEIGHMENT DATA
# -------------------------

def parse_data(text):

    data = {}

    data["rst"] = find(r"RST\s*:\s*(\d+)", text)
    data["vehicle"] = find(r"Vehicle No\s*:\s*([A-Z0-9]+)", text)
    data["party"] = find(r"PARTY NAME\s*:\s*([A-Z ]+)", text)
    data["place"] = find(r"PLACE\s*:\s*([A-Z]+)", text)
    data["material"] = find(r"MATERIAL\s*:\s*([A-Z ]+)", text)

    data["gross"] = find(r"Gross\.\s*:\s*(\d+)", text)
    data["tare"] = find(r"Tare\.\s*:\s*(\d+)", text)
    data["net"] = find(r"Net\.\s*:\s*(\d+)", text)

    data["date"] = find(r"(\d{2}-[A-Za-z]{3}-\d{2})", text)
    data["time"] = find(r"(\d{1,2}:\d{2}:\d{2}\s*[AP]M)", text)

    return data


# -------------------------
# FETCH EMAILS
# -------------------------

def fetch_slips():

    slips = []
    seen_rst = set()

    try:

        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, 'SUBJECT "WEIGHMENT"')

        mail_ids = messages[0].split()

        # check last 50 emails
        for num in reversed(mail_ids[-50:]):

            status, msg_data = mail.fetch(num, "(RFC822)")

            for response in msg_data:

                if isinstance(response, tuple):

                    msg = email.message_from_bytes(response[1])

                    for part in msg.walk():

                        if part.get_content_type() == "application/pdf":

                            pdf_data = part.get_payload(decode=True)

                            text = read_pdf(pdf_data)

                            data = parse_data(text)

                         if data["rst"] not in seen_rst:
                             slips.append(data)
                             seen_rst.add(data["rst"])

    except Exception as e:

        print("MAIL ERROR:", e)

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