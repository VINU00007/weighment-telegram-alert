import os
import imaplib
import email
from email.header import decode_header
import pdfplumber
from io import BytesIO
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ContextTypes
)

# -------------------------------------------------------------------
# LOAD ENVIRONMENT VARIABLES
# -------------------------------------------------------------------

load_dotenv()

IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID   = int(os.getenv("CHAT_ID"))

# -------------------------------------------------------------------
# TIME HELPERS
# -------------------------------------------------------------------

def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def format_dt(dt):
    if not dt:
        return "N/A"
    return dt.strftime("%d-%b-%Y | %I:%M %p")

# -------------------------------------------------------------------
# EMAIL/ PDF HELPERS
# -------------------------------------------------------------------

def safe_decode(v):
    if not v:
        return ""
    parts = decode_header(v)
    decoded = []
    for p, enc in parts:
        if isinstance(p, bytes):
            decoded.append(p.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(p)
    return "".join(decoded)

def pick(text, pattern):
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""

def clean_material(m):
    if not m:
        return ""
    m = m.replace("CELL", "").replace("NO", "")
    return re.sub(r"\s+", " ", m).strip()

def parse_dt(s):
    if not s:
        return None
    fmts = ["%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None

def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        return {}

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    material = pick(text, r"MATERIAL\s*:\s*(.+?)\s+(?:CELL|NO|$)")
    material = clean_material(material)

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)"),
        "Material": material,
        "GrossKg": pick(text, r"Gross\.?:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.?:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross.*?Kgs.*?" + dt_pat),
        "TareDT": pick(text, r"Tare.*?Kgs.*?" + dt_pat)
    }

# -------------------------------------------------------------------
# EMAIL SCANNING
# -------------------------------------------------------------------

def scan_email_latest():
    yard = {}

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    _, data = mail.uid("search", None, "ALL")
    uids = data[0].split()
    if not uids:
        return {}

    for uid in uids[-30:]:   # last 30 mails
        _, msg_data = mail.uid("fetch", uid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        subject = safe_decode(msg.get("Subject")).upper()
        if "WEIGH" not in subject and "SLIP" not in subject:
            continue

        for part in msg.walk():
            if "pdf" in part.get_content_type():
                info = extract_from_pdf(part.get_payload(decode=True))
                if not info or not info.get("RST"):
                    continue

                rst = info["RST"]
                yard[rst] = info

    mail.logout()
    return yard

# -------------------------------------------------------------------
# TELEGRAM BOT HANDLERS
# -------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📥 Scan Latest Slips", callback_data="scan")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    reply = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 Hello Vinu!\nYour Rice Mill Telegram Assistant is ready.\n\nChoose an option:",
        reply_markup=reply
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_chat.id != ADMIN_ID:
        return

    if query.data == "scan":
        yard = scan_email_latest()
        if not yard:
            await query.edit_message_text("No weighment slips found in last 30 mails.")
            return

        msg = "📥 *Latest Weighment Slips Found:*\n\n"
        for rst, d in yard.items():
            msg += (
                f"📌 *RST {rst}*\n"
                f"🚛 {d['Vehicle']}\n"
                f"🌾 {d['Material']}\n"
                f"⚖ Gross: {d['GrossKg']} | Tare: {d['TareKg']}\n\n"
            )

        await query.edit_message_text(msg, parse_mode="Markdown")

    elif query.data == "help":
        await query.edit_message_text(
            "🆘 *Help Menu*\n\n"
            "• Press 'Scan Latest Slips' to fetch weight slips.\n"
            "• I will later add options like search by RST, vehicle, date etc.",
            parse_mode="Markdown"
        )

# -------------------------------------------------------------------
# RUN BOT
# -------------------------------------------------------------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))

    print("BOT RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()