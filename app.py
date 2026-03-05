import imaplib
import email
import pdfplumber
import os
import asyncio
import io
import json
import re
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


def extract_between(text, start, end):
    try:
        return text.split(start)[1].split(end)[0].strip()
    except:
        return "-"


def parse_pdf(data):

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = ""
        for p in pdf.pages:
            t = p.extract_text()
            if t:
                text += t + " "

    text = " ".join(text.split())

    rst = extract_between(text, "RST :", "Vehicle No")
    vehicle = extract_between(text, "Vehicle No :", "PARTY NAME")
    party = extract_between(text, "PARTY NAME :", "PLACE")
    place = extract_between(text, "PLACE :", "MATERIAL")
    material = extract_between(text, "MATERIAL :", "CELL")

    gross = "-"
    tare = "-"
    net = "-"
    gross_time = "-"
    tare_time = "-"

    g = re.search(r"Gross\.\s*:\s*(\d+)\s*Kgs\s*(\d{2}-\w{3}-\d{2})\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)", text)
    if g:
        gross = g.group(1)
        gross_time = f"{g.group(2)} {g.group(3)}"

    t = re.search(r"Tare\.\s*:\s*(\d+)\s*Kgs\s*(\d{2}-\w{3}-\d{2})\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)", text)
    if t:
        tare = t.group(1)
        tare_time = f"{t.group(2)} {t.group(3)}"

    n = re.search(r"Net\.\s*:\s*(\d+)", text)
    if n:
        net = n.group(1)

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

    text = "⚖️ LAST 5 WEIGHMENTS\n\n"

    for w in last_weighments[-5:]:
        text += w + "\n"

    await callback.message.answer(text)


async def main():

    asyncio.create_task(monitor())
    await dp.start_polling(bot)


asyncio.run(main())