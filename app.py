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
processed = {}
history = []


# -----------------------------
# PDF PARSER
# -----------------------------
def parse_pdf(data):

    doc = fitz.open(stream=data, filetype="pdf")
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
    gross = find(r"Gross.*?(\d+)\s*Kgs")
    tare = find(r"Tare.*?(\d+)\s*Kgs")

    times = re.findall(r"\d{1,2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M", text)

    t1 = None
    t2 = None

    if len(times) >= 1:
        t1 = datetime.strptime(times[0], "%d-%b-%y %I:%M:%S %p")

    if len(times) >= 2:
        t2 = datetime.strptime(times[1], "%d-%b-%y %I:%M:%S %p")

    return {
        "rst": rst,
        "vehicle": vehicle,
        "party": party,
        "place": place,
        "material": material,
        "gross": gross,
        "tare": tare,
        "t1": t1,
        "t2": t2
    }


# -----------------------------
# EMAIL FETCHER
# -----------------------------
def fetch_mails():

    slips = []

    try:

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        _, data = mail.search(None, "ALL")
        ids = data[0].split()[-50:]

        for num in ids:

            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            for part in msg.walk():

                if part.get_content_type() == "application/pdf":

                    pdf = part.get_payload(decode=True)
                    slip = parse_pdf(pdf)
                    slips.append(slip)

        mail.logout()

    except Exception as e:
        print("MAIL ERROR:", e)

    return slips


# -----------------------------
# MONITOR LOOP
# -----------------------------
async def monitor():

    while True:

        slips = fetch_mails()

        for s in slips:

            rst = s["rst"]

            if rst == "-":
                continue

            # FIRST WEIGHMENT
            if rst not in processed:

                processed[rst] = s

                weight = s["gross"] if s["gross"] != "-" else s["tare"]
                time = s["t1"]

                if CHAT_ID and time:

                    msg = f"""
⚖️ WEIGHMENT ALERT

🧾 RST : {rst} | 🚛 {s['vehicle']}
🏢 Party : {s['party']}
📍 Place : {s['place']}
🌾 Material : {s['material']}

⚖ Weight : {weight} Kg
🕒 {time.strftime("%d-%b-%y | %I:%M:%S %p")}

🟡 STATUS : VEHICLE ENTERED YARD
"""

                    await bot.send_message(CHAT_ID, msg)

            # SECOND WEIGHMENT
            else:

                prev = processed[rst]

                if prev["t2"] is None and s["t2"]:

                    entry = min(s["t1"], s["t2"])
                    exit = max(s["t1"], s["t2"])

                    yard = exit - entry

                    net = "-"
                    if s["gross"] != "-" and s["tare"] != "-":
                        net = int(s["gross"]) - int(s["tare"])

                    if CHAT_ID:

                        msg = f"""
⚖️ WEIGHMENT COMPLETED

🧾 RST : {rst} | 🚛 {s['vehicle']}
🏢 Party : {s['party']}
📍 Place : {s['place']}
🌾 Material : {s['material']}

⚖ Gross : {s['gross']}
⚖ Tare  : {s['tare']}
📦 Net   : {net}

⏱ Yard Time : {yard}

🕒 Exit : {exit.strftime("%d-%b-%y | %I:%M:%S %p")}
"""

                        await bot.send_message(CHAT_ID, msg)

                    history.append(s)

        await asyncio.sleep(20)


# -----------------------------
# START COMMAND
# -----------------------------
@dp.message(Command("start"))
async def start(msg: types.Message):

    global CHAT_ID
    CHAT_ID = msg.chat.id

    await msg.answer(
        "✅ Weighment bot connected.\n"
        "Real-time alerts will appear here."
    )


# -----------------------------
# LATEST COMMAND
# -----------------------------
@dp.message(Command("latest"))
async def latest(msg: types.Message):

    if not history:
        await msg.answer("No weighments found.")
        return

    out = "📥 Latest Weighments\n\n"

    for s in history[-20:]:

        net = "-"
        if s["gross"] != "-" and s["tare"] != "-":
            net = int(s["gross"]) - int(s["tare"])

        time = s["t2"] if s["t2"] else s["t1"]

        out += f"""
RST {s['rst']} | {s['vehicle']}
{time.strftime("%d-%b-%y | %I:%M:%S %p")}
{s['party']} | {s['material']}
Gross {s['gross']} | Tare {s['tare']} | Net {net}

"""

    await msg.answer(out)


# -----------------------------
# YARD COMMAND
# -----------------------------
@dp.message(Command("yard"))
async def yard(msg: types.Message):

    out = "🚛 Trucks In Yard\n\n"

    for r, s in processed.items():

        if s["t2"] is None and s["t1"]:

            out += f"""
RST {s['rst']} | {s['vehicle']}
{s['material']}
Entered : {s['t1'].strftime("%d-%b-%y | %I:%M:%S %p")}

"""

    await msg.answer(out)


# -----------------------------
# MAIN
# -----------------------------
async def main():

    asyncio.create_task(monitor())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())