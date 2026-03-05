import imaplib
import email
import fitz
import re
import os
import asyncio
from datetime import datetime
from aiogram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=BOT_TOKEN)

sent_events = set()


def parse_pdf(pdf_bytes):

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    text = ""
    for page in doc:
        text += page.get_text()

    raw = text
    text = re.sub(r"\s+", " ", text)

    def find(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    rst = find(r"RST\s*:\s*(\d+)")
    vehicle = find(r"Vehicle\s*No\s*:\s*([A-Z0-9]+)")
    party = find(r"PARTY\s*NAME\s*:? ([A-Za-z\s]+?) PLACE")
    place = find(r"PLACE\s*:\s*([A-Z]+)")
    material = find(r"MATERIAL\s*:\s*([A-Z\s]+?) CELL")

    gross = "-"
    tare = "-"
    net = "-"
    gross_time = "-"
    tare_time = "-"

    # ---- gross line ----
    g = re.search(
        r"Gross\.\s*:\s*(\d+)\s*Kgs?\s*(\d{2}-[A-Za-z]{3}-\d{2})?\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)?",
        raw,
    )

    if g:
        gross = g.group(1)
        if g.group(2) and g.group(3):
            gross_time = f"{g.group(2)} {g.group(3)}"

    # ---- tare line ----
    t = re.search(
        r"Tare\.\s*:\s*(\d+)\s*Kgs?\s*(\d{2}-[A-Za-z]{3}-\d{2})?\s*(\d{1,2}:\d{2}:\d{2}\s*[AP]M)?",
        raw,
    )

    if t:
        tare = t.group(1)
        if t.group(2) and t.group(3):
            tare_time = f"{t.group(2)} {t.group(3)}"

    # ---- net ----
    n = re.search(r"Net\.\s*:\s*(\d+)", raw)
    if n:
        net = n.group(1)

    yard_time = "-"

    try:
        if gross_time != "-" and tare_time != "-":

            gdt = datetime.strptime(gross_time, "%d-%b-%y %I:%M:%S %p")
            tdt = datetime.strptime(tare_time, "%d-%b-%y %I:%M:%S %p")

            diff = abs(gdt - tdt)

            h = diff.seconds // 3600
            m = (diff.seconds % 3600) // 60
            s = diff.seconds % 60

            yard_time = f"{h}h {m}m {s}s"

    except:
        pass

    return rst, vehicle, party, place, material, gross, tare, net, gross_time, tare_time, yard_time


def check_mail():

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    result, data = mail.uid("search", None, "ALL")

    ids = data[0].split()[-10:]

    slips = []

    for uid in ids:

        result, msg_data = mail.uid("fetch", uid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        for part in msg.walk():

            if part.get_content_type() == "application/pdf":

                pdf_bytes = part.get_payload(decode=True)

                slips.append(parse_pdf(pdf_bytes))

    return slips


async def monitor():

    while True:

        try:

            slips = check_mail()

            for data in slips:

                rst, vehicle, party, place, material, gross, tare, net, gt, tt, yard = data

                event_id = f"{rst}_{net}"

                if event_id in sent_events:
                    continue

                sent_events.add(event_id)

                if net != "-":
                    status = "🟢 STATUS : VEHICLE APPROVED FOR GATE PASS"
                    yard_status = f"⏱ Yard Time : {yard}"
                else:
                    status = "🟡 STATUS : SECOND WEIGHMENT PENDING"
                    yard_status = "⏱ Yard Status : VEHICLE IN YARD"

                message = f"""
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

                await bot.send_message(CHAT_ID, message)

        except Exception as e:
            print("MAIL ERROR:", e)

        await asyncio.sleep(30)


async def main():

    await bot.delete_webhook(drop_pending_updates=True)

    print("BOT RUNNING — WEIGHMENT PARSER ACTIVE")

    await monitor()


if __name__ == "__main__":
    asyncio.run(main())