import imaplib
import email
import pdfplumber
import os
import asyncio
import io
import json
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = int(os.getenv("CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
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


def parse_pdf(data):

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = ""
        for p in pdf.pages:
            t = p.extract_text()
            if t:
                text += t + "\n"

    lines = text.split("\n")

    rst = "-"
    vehicle = "-"
    party = "-"
    place = "-"
    material = "-"
    gross = "-"
    tare = "-"
    net = "-"
    gross_time = "-"
    tare_time = "-"

    for line in lines:

        if "RST" in line and ":" in line:
            rst = line.split(":")[1].strip()

        if "Vehicle" in line and ":" in line:
            vehicle = line.split(":")[1].strip()

        if "PARTY" in line and ":" in line:
            party = line.split(":")[1].strip()

        if "PLACE" in line and ":" in line:
            place = line.split(":")[1].strip()

        if "MATERIAL" in line and ":" in line:
            material = line.split(":")[1].strip()

        if "Gross" in line:
            parts = line.split()
            for p in parts:
                if p.isdigit():
                    gross = p
                    break
            gross_time = " ".join(parts[-3:])

        if "Tare" in line:
            parts = line.split()
            for p in parts:
                if p.isdigit():
                    tare = p
                    break
            tare_time = " ".join(parts[-3:])

        if "Net" in line:
            parts = line.split()
            for p in parts:
                if p.isdigit():
                    net = p
                    break

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time


def read_mail():

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    r, d = mail.uid("search", None, "ALL")

    ids = d[0].split()[-100:]

    slips = []

    for i in ids:

        r, data = mail.uid("fetch", i, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])

        for p in msg.walk():

            if p.get_content_type() == "application/pdf":

                slips.append(parse_pdf(p.get_payload(decode=True)))

    mail.logout()

    return slips


async def monitor():

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Last 5 Weighments", callback_data="last5")]
        ]
    )

    while True:

        try:

            slips = read_mail()

            for s in slips:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt = s

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

                await bot.send_message(CHAT_ID, msg, reply_markup=keyboard)

        except Exception as e:
            print("MAIL ERROR:", e)

        await asyncio.sleep(20)


@dp.callback_query(lambda c: c.data == "last5")
async def show_last5(callback: types.CallbackQuery):

    if not last_weighments:
        await callback.message.answer("No weighments available")
        return

    text = "⚖️ LAST 5 WEIGHMENTS\n\n"

    for w in last_weighments[-5:]:
        text += w + "\n"

    await callback.message.answer(text)


async def main():

    asyncio.create_task(monitor())

    await dp.start_polling(bot)


asyncio.run(main())