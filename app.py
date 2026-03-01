import imaplib
import email
from email.header import decode_header
import re
import asyncio
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ------------------------
# CONFIG
# ------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your-email@gmail.com"
IMAP_PASS = "your-app-password"

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = -1001234567890       # your group id


# ------------------------
# MAIL PARSER
# ------------------------
def parse_rst_details(text):
    """Extract RST, vehicle, material, gross/tare timestamps."""
    patterns = {
        "rst": r"RST\s*[:\- ]\s*(\d+)",
        "vehicle": r"Vehicle\s*[:\- ]\s*([A-Z0-9]+)",
        "material": r"Material\s*[:\- ]\s*([A-Za-z ]+)",
        "gross": r"Gross\s*[:\- ]\s*(\d+)?",
        "tare": r"Tare\s*[:\- ]\s*(\d+)?",
        "datetime": r"Date\s*[:\- ]\s*([0-9\-: ]+)",
    }

    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        result[key] = match.group(1).strip() if match else None

    return result


def fetch_latest_weighments(limit=10):
    """Fetch last N weighment slips from Gmail inbox."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        _, search_data = mail.search(None, '(SUBJECT "Weighment Slip")')
        mail_ids = search_data[0].split()

        if not mail_ids:
            return []

        latest_ids = mail_ids[-limit:]
        slips = []

        for msg_id in reversed(latest_ids):
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            parts = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        parts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
            else:
                parts.append(msg.get_payload(decode=True).decode("utf-8", errors="ignore"))

            full_text = "\n".join(parts)
            parsed = parse_rst_details(full_text)
            slips.append(parsed)

        return slips

    except Exception as e:
        return [{"error": str(e)}]


# ------------------------
# BOT UI
# ------------------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Latest Weighments", callback_data="latest")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome Vinu!*\nChoose an option below:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ------------------------
# BUTTON HANDLER
# ------------------------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "latest":
        slips = fetch_latest_weighments()

        if not slips:
            await query.edit_message_text("No weighment slips found.")
            return

        msg = "📥 *Latest Weighment Slips*\n\n"

        for s in slips:
            rst = s.get("rst") or "-"
            vehicle = s.get("vehicle") or "-"
            material = s.get("material") or "-"
            gross = s.get("gross") or "-"
            tare = s.get("tare") or "-"
            dt = s.get("datetime") or "-"

            msg += (
                f"• *RST:* {rst}\n"
                f"  🚛 {vehicle}\n"
                f"  🌾 {material}\n"
                f"  ⚖ Gross: {gross} | Tare: {tare}\n"
                f"  🕒 Time: {dt}\n\n"
            )

        await query.edit_message_text(msg, parse_mode="Markdown")

    elif query.data == "help":
        await query.edit_message_text(
            "❓ *Help Menu*\n\n"
            "• Click *Latest Weighments* to fetch last slips.\n"
            "• Real-time processing will be added soon.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


# ------------------------
# MAIN ASYNC BOOTSTRAP
# ------------------------
async def run_bot():
    print("BOT RUNNING...")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()


if __name__ == "__main__":
    asyncio.run(run_bot())
