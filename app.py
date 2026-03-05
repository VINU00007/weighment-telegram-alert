import imaplib
import email
import pdfplumber
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

        if "RST" in line:
            rst = line.split(":")[-1].strip()

        if "Vehicle" in line:
            vehicle = line.split(":")[-1].strip()

        if "PARTY" in line:
            party = line.split(":")[-1].strip()

        if "PLACE" in line:
            place = line.split(":")[-1].strip()

        if "MATERIAL" in line:
            material = line.split(":")[-1].strip()

        if "Gross" in line:
            gross = line.split(":")[-1].replace("Kgs","").strip()

        if "Tare" in line:
            tare = line.split(":")[-1].replace("Kgs","").strip()

        if "Net" in line:
            net = line.split(":")[-1].replace("Kgs","").strip()

    yard = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            g = datetime.strptime(gross_time,"%d-%b-%y %I:%M:%S %p")
            t = datetime.strptime(tare_time,"%d-%b-%y %I:%M:%S %p")

            d = abs(g-t)

            h = d.seconds//3600
            m = (d.seconds%3600)//60

            yard = f"{h}h {m}m"

    except:
        pass

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time, yard


def read_mail():

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    r, d = mail.uid("search", None, "ALL")

    ids = d[0].split()[-5:]

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
⚖ Tare : {tare} Kg

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
