import os
import imaplib
import email
import pdfplumber
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# -----------------------------
#   ENV VARIABLES
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_SERVER = os.getenv("EMAIL_SERVER", "imap.gmail.com")
LAST_UID_FILE = "last_uid.txt"

# -----------------------------
#   UTILITIES
# -----------------------------

def extract_pdf_text(path):
    """Extract text from a PDF."""
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join([page.extract_text() or "" for page in pdf.pages])
        return text
    except:
        return ""

def parse_weighment(text):
    """Extract weighment slip info from text."""
    lines = text.splitlines()
    data = {
        "rst": "",
        "truck": "",
        "material": "",
        "gross": "",
        "tare": "",
        "party": "",
        "time1": "",
        "time2": ""
    }

    for line in lines:
        L = line.strip()
        if L.startswith("RST"):
            data["rst"] = L.replace("RST", "").strip()
        if "TRUCK" in L.upper():
            data["truck"] = L.split(":")[-1].strip()
        if "MATERIAL" in L.upper():
            data["material"] = L.split(":")[-1].strip()
        if "GROSS" in L.upper():
            data["gross"] = L.split(":")[-1].strip()
        if "TARE" in L.upper():
            data["tare"] = L.split(":")[-1].strip()
        if "PARTY" in L.upper():
            data["party"] = L.split(":")[-1].strip()
        if "FIRST WEIGHMENT" in L.upper():
            data["time1"] = L.split(":")[-1].strip()
        if "SECOND WEIGHMENT" in L.upper():
            data["time2"] = L.split(":")[-1].strip()

    # yard time calculation
    if data["time1"] and data["time2"]:
        try:
            t1 = datetime.strptime(data["time1"], "%d-%m-%Y %H:%M:%S")
            t2 = datetime.strptime(data["time2"], "%d-%m-%Y %H:%M:%S")
            diff = t2 - t1
            hours, remainder = divmod(diff.seconds, 3600)
            minutes = remainder // 60
            data["yard"] = f"{hours}h {minutes}m"
        except:
            data["yard"] = ""
    else:
        data["yard"] = ""

    return data


def format_weighment(d):
    """Nicely formatted message."""
    return (
        f"📌 *RST {d['rst']}*\n"
        f"🚛 *{d['truck']}*\n"
        f"🏭 *Party:* {d['party']}\n"
        f"🌾 *Material:* {d['material']}\n"
        f"⚖ *Gross:* {d['gross']}   |   *Tare:* {d['tare']}\n"
        f"⏱ *Yard Time:* {d['yard']}\n"
    )


# -----------------------------
#   MAIL SCANNER
# -----------------------------

async def scan_inbox(app):
    """Continuously checks inbox for new weighment slips."""
    await asyncio.sleep(5)

    while True:
        try:
            mail = imaplib.IMAP4_SSL(EMAIL_SERVER)
            mail.login(EMAIL_USER, EMAIL_PASS)
            mail.select("inbox")

            result, data = mail.search(None, '(UNSEEN SUBJECT "WEIGHMENT")')
            uids = data[0].split()

            for uid in uids:
                res, msg_data = mail.fetch(uid, "(RFC822)")
                raw = email.message_from_bytes(msg_data[0][1])

                pdf_path = None
                for part in raw.walk():
                    if part.get_content_type() == "application/pdf":
                        filename = "slip.pdf"
                        pdf_path = filename
                        with open(pdf_path, "wb") as f:
                            f.write(part.get_payload(decode=True))

                if pdf_path:
                    text = extract_pdf_text(pdf_path)
                    slip = parse_weighment(text)

                    message = format_weighment(slip)

                    await app.bot.send_message(
                        chat_id=CHAT_ID,
                        text="🚨 *NEW WEIGHMENT RECEIVED*\n\n" + message,
                        parse_mode="Markdown"
                    )

            mail.logout()

        except Exception as e:
            print("SCAN ERROR:", e)

        await asyncio.sleep(20)


# -----------------------------
#   BOT HANDLERS
# -----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome Vinu! Bot is live 🔥")


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📥 Latest 5 Weighments", callback_data="latest"),
        ],
        [
            InlineKeyboardButton("ℹ Help", callback_data="help"),
        ]
    ]

    await update.message.reply_text(
        "Choose an option:",  
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        await query.edit_message_text("Send /menu anytime to view options.")
        return

    if query.data == "latest":
        await query.edit_message_text("Fetching last 5 slips...")
        # (We will add stored DB version later)

# -----------------------------
#   MAIN
# -----------------------------

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CallbackQueryHandler(handle_buttons))

    # background scanning
    asyncio.create_task(scan_inbox(app))

    print("BOT RUNNING...")
    await app.run_polling(close_loop=False)


# -----------------------------
#   RAILWAY-SAFE LAUNCHER
# -----------------------------

if __name__ == "__main__":
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.create_task(main())
    loop.run_forever()
