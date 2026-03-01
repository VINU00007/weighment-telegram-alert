import asyncio
import imaplib
import email
from email.header import decode_header
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# -----------------------------
# CONFIG
# -----------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your-email@gmail.com"
IMAP_PASS = "your-app-password"

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"


# -----------------------------
# MAIL PARSING
# -----------------------------
def parse_rst_details(text):
    patterns = {
        "rst": r"RST\s*[:\- ]\s*(\d+)",
        "vehicle": r"Vehicle\s*[:\- ]\s*([A-Z0-9]+)",
        "material": r"Material\s*[:\- ]\s*([A-Za-z ]]+)",
        "gross": r"Gross\s*[:\- ]\s*(\d+)?",
        "tare": r"Tare\s*[:\- ]\s*(\d+)?",
        "date": r"Date\s*[:\- ]\s*([0-9\-: ]+)",
    }

    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        result[key] = match.group(1).strip() if match else "-"

    return result


def fetch_latest_weighments(limit=10):
    """Fetch last N weighment mails."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        _, search_data = mail.search(None, '(SUBJECT "Weighment Slip")')
        mail_ids = search_data[0].split()

        slips = []
        for msg_id in mail_ids[-limit:]:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            content = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        content += part.get_payload(decode=True).decode("utf-8", errors="ignore")
            else:
                content += msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            slips.append(parse_rst_details(content))

        return slips

    except Exception as e:
        return [{"error": str(e)}]


# -----------------------------
# BOT UI
# -----------------------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Latest Weighments", callback_data="latest")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome Vinu!\nChoose an option below:",
        reply_markup=main_menu()
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "latest":
        slips = fetch_latest_weighments()

        msg = "📥 *Latest Weighment Slips*\n\n"

        for s in slips:
            msg += (
                f"• *RST:* {s['rst']}\n"
                f"  🚛 {s['vehicle']}\n"
                f"  🌾 {s['material']}\n"
                f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
                f"  🕒 Time: {s['date']}\n\n"
            )

        await query.edit_message_text(msg, parse_mode="Markdown")

    elif query.data == "help":
        await query.edit_message_text(
            "❓ *Help Menu*\n\n"
            "• Click Latest Weighments to fetch last slips.\n",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )


# -----------------------------
# MAIN — THIS WILL NEVER CRASH
# -----------------------------
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))

    print("BOT RUNNING...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
