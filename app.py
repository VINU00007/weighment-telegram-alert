import imaplib
import email
import os
import asyncio
import json
import re
import fitz
from email.utils import parsedate_to_datetime
from aiohttp import ClientTimeout
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = int(os.getenv("CHAT_ID"))

WEIGHBRIDGE_EMAIL = "weighbridge@email.com"

bot = Bot(
    token=BOT_TOKEN,
    timeout=ClientTimeout(total=60)
)

dp = Dispatcher()

STATE_FILE = "processed.json"

if os.path.exists(STATE_FILE):
    with open(STATE_FILE) as f:
        sent = set(json.load(f))
else:
    sent = set()

last_weighments = []


def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(list(sent), f)


def extract_pdf_text(data):
    text = ""
    doc = fitz.open(stream=data, filetype="pdf")
    for page in doc:
        text += page.get_text()
    return " ".join(text.split())


def get(pattern, text):
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else "-"


def parse_pdf(data):

    text = extract_pdf_text(data)

    rst = get(r"RST\s*:\s*(\d+)", text)
    vehicle = get(r"Vehicle\s*No\s*:\s*([A-Z0-9]+)", text)
    party = get(r"PARTY\s*NAME\s*:\s*(.*?)\s+PLACE", text)
    place = get(r"PLACE\s*:\s*(.*?)\s+MATERIAL", text)
    material = get(r"MATERIAL\s*:\s*(.*?)\s+CELL", text)

    gross = "-"
    tare = "-"
    net = "-"
    gross_time = "-"
    tare_time = "-"

    g = re.search(
        r"Gross\.\s*:\s*(\d+)\s*Kgs\s*(\d{2}-\w{3}-\d{2})\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        text,
    )

    if g:
        gross = g.group(1)
        gross_time = f"{g.group(2)} {g.group(3)}"

    t = re.search(
        r"Tare\.\s*:\s*(\d+)\s*Kgs\s*(\d{2}-\w{3}-\d{2})\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        text,
    )

    if t:
        tare = t.group(1)
        tare_time = f"{t.group(2)} {t.group(3)}"

    n = re.search(r"Net\.\s*:\s*(\d+)", text)

    if n:
        net = n.group(1)

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time


async def monitor():

    while True:

        try:

            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(EMAIL_USER, EMAIL_PASS)
            mail.select("inbox")

            r, d = mail.uid("search", None, f'(FROM "{WEIGHBRIDGE_EMAIL}")')

            ids = d[0].split()[-20:]

            slips = []

            for i in ids:

                r, data = mail.uid("fetch", i, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])

                date = parsedate_to_datetime(msg["Date"])

                for part in msg.walk():

                    if part.get_content_type() == "application/pdf":

                        pdf_data = part.get_payload(decode=True)

                        parsed = parse_pdf(pdf_data)

                        slips.append((date, parsed))

            mail.logout()

            slips.sort(key=lambda x: x[0])

            for s in slips:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt = s[1]

                if net != "-":
                    key = f"{rst}_final"
                    status = "🟢 STATUS : TRUCK READY FOR GATE PASS"
                else:
                    key = f"{rst}_first"
                    status = "🟡 STATUS : TRUCK ENTERED YARD"

                if key in sent:
                    continue

                sent.add(key)
                save_state()

                msg = f"""
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

{status}
"""

                last_weighments.append(msg)

                if len(last_weighments) > 20:
                    last_weighments.pop(0)

                await bot.send_message(CHAT_ID, msg)

        except Exception as e:

            print("MAIL ERROR:", e)

        await asyncio.sleep(10)


@dp.message(Command("last5"))
async def last5(message: Message):

    if not last_weighments:
        await message.answer("No weighments available")
        return

    text = "⚖️ LAST 5 WEIGHMENTS\n\n"

    for w in last_weighments[-5:]:
        text += w + "\n"

    await message.answer(text)


async def main():

    # Prevent Telegram conflict errors
    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(monitor())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())