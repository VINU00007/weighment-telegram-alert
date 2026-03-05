import imaplib
import email
import pdfplumber
import re
import os
import asyncio
import io
import json
from datetime import datetime
from aiogram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = int(os.getenv("CHAT_ID"))

bot = Bot(token=BOT_TOKEN)

STATE_FILE = "processed.json"

if os.path.exists(STATE_FILE):
    with open(STATE_FILE) as f:
        sent = set(json.load(f))
else:
    sent = set()


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

    text = re.sub(r"\s+", " ", text)

    def get(p):
        m = re.search(p, text, re.I)
        return m.group(1).strip() if m else "-"

    rst = get(r"RST\s*:\s*(\d+)")
    vehicle = get(r"Vehicle\s*No\s*:\s*([A-Z0-9]+)")
    party = get(r"PARTY\s*NAME\s*:\s*(.*?) PLACE")
    place = get(r"PLACE\s*:\s*(\w+)")
    material = get(r"MATERIAL\s*:\s*(.*?) CELL")

    gross = "-"
    tare = "-"
    net = "-"

    gross_time = "-"
    tare_time = "-"

    g = re.search(
        r"Gross\.\s*:\s*(\d+)\s*Kgs.*?(\d{2}-[A-Za-z]{3}-\d{2}).*?(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        text,
        re.S,
    )

    if g:
        gross = g.group(1)
        gross_time = f"{g.group(2)} {g.group(3)}"

    t = re.search(
        r"Tare\.\s*:\s*(\d+)\s*Kgs.*?(\d{2}-[A-Za-z]{3}-\d{2}).*?(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        text,
        re.S,
    )

    if t:
        tare = t.group(1)
        tare_time = f"{t.group(2)} {t.group(3)}"

    n = re.search(r"Net\.\s*:\s*(\d+)", text)

    if n:
        net = n.group(1)

    yard = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            g = datetime.strptime(gross_time, "%d-%b-%y %I:%M:%S %p")
            t = datetime.strptime(tare_time, "%d-%b-%y %I:%M:%S %p")

            d = abs(g - t)

            h = d.seconds // 3600
            m = (d.seconds % 3600) // 60

            yard = f"{h}h {m}m"

    except:
        pass

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time, yard


def read_mail():

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    r, d = mail.uid("search", None, "ALL")

    ids = d[0].split()[-10:]

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

    while True:

        try:

            slips = read_mail()

            for s in slips:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt, yard = s

                if net != "-":
                    key = f"{rst}_final"
                else:
                    key = f"{rst}_first"

                if key in sent:
                    continue

                sent.add(key)
                save_state()

                if net != "-":

                    status = "🟢 STATUS : TRUCK READY FOR GATE PASS"
                    yard_status = f"⏱ Yard Time : {yard}"

                else:

                    status = "🟡 STATUS : TRUCK ENTERED YARD"
                    yard_status = "⏱ Yard Status : VEHICLE IN YARD"

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

{yard_status}
{status}
"""

                await bot.send_message(CHAT_ID, msg)

        except Exception as e:
            print("MAIL ERROR:", e)

        await asyncio.sleep(20)


async def main():

    await bot.delete_webhook(drop_pending_updates=True)

    print("WEIGHMENT ALERT BOT RUNNING")

    await monitor()


asyncio.run(main())
