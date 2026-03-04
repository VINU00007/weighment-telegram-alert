import os
import asyncio
import imaplib
import email
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message
import fitz  # PyMuPDF

# -----------------------------
# ENV VARIABLES (Railway)
# -----------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = os.getenv("CHAT_ID")

IMAP_SERVER = "imap.gmail.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# -----------------------------
# PDF TEXT EXTRACTOR
# -----------------------------

def read_pdf(data):

    text = ""

    pdf = fitz.open(stream=data, filetype="pdf")

    for page in pdf:
        text += page.get_text()

    return text


# -----------------------------
# PARSE WEIGHMENT DATA
# -----------------------------

def parse_data(text):

    result = {
        "rst": "-",
        "vehicle": "-",
        "party": "-",
        "place": "-",
        "material": "-",
        "gross": "-",
        "tare": "-",
        "time": "-"
    }

    lines = text.split("\n")

    for line in lines:

        if "RST" in line.upper():
            result["rst"] = line.split()[-1]

        if "Vehicle" in line:
            result["vehicle"] = line.split()[-1]

        if "Party" in line:
            result["party"] = line.replace("Party", "").strip()

        if "Place" in line:
            result["place"] = line.replace("Place", "").strip()

        if "Material" in line:
            result["material"] = line.replace("Material", "").strip()

        if "Gross" in line:
            result["gross"] = line.split()[-1]

        if "Tare" in line:
            result["tare"] = line.split()[-1]

    return result


# -----------------------------
# FETCH EMAILS
# -----------------------------

def fetch_slips():

    slips = []

    try:

        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, "ALL")

        mail_ids = messages[0].split()

        for num in mail_ids[-10:]:

            status, msg_data = mail.fetch(num, "(RFC822)")

            for response_part in msg_data:

                if isinstance(response_part, tuple):

                    msg = email.message_from_bytes(response_part[1])

                    for part in msg.walk():

                        if part.get_content_type() == "application/pdf":

                            pdf_data = part.get_payload(decode=True)

                            text = read_pdf(pdf_data)

                            slips.append(parse_data(text))

    except Exception as e:

        return str(e)

    return slips


# -----------------------------
# TELEGRAM COMMAND
# -----------------------------

@dp.message(CommandStart())
async def start(message: Message):

    slips = fetch_slips()

    if isinstance(slips, str):
        await message.answer(f"⚠ Error: {slips}")
        return

    if len(slips) == 0:
        await message.answer("⚠ No weighment slips found.")
        return

    msg = "📥 Latest Weighment Slips\n\n"

    for s in slips:

        msg += (
            f"• RST: {s['rst']}\n"
            f"  🚛 Vehicle: {s['vehicle']}\n"
            f"  🏢 Party: {s['party']}\n"
            f"  📍 Place: {s['place']}\n"
            f"  🌾 Material: {s['material']}\n"
            f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
            f"  🕒 Time: {s['time']}\n\n"
        )

    await message.answer(msg)


# -----------------------------
# RUN BOT
# -----------------------------

async def main():

    print("BOT RUNNING — PDF READER ACTIVE")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())