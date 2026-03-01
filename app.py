import asyncio
import imaplib
import email
from email.header import decode_header
import re
from aiogram import Bot, Dispatcher, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your-email@gmail.com"
IMAP_PASS = "your-app-password"

BOT_TOKEN = "YOUR_BOT_TOKEN"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# -----------------------------
# MAIL PARSING
# -----------------------------
def parse_rst(text):
    def grab(pat):
        m = re.search(pat, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": grab(r"RST\s*[:\- ]\s*(\d+)"),
        "vehicle": grab(r"Vehicle\s*[:\- ]\s*([A-Z0-9]+)"),
        "material": grab(r"Material\s*[:\- ]\s*([A-Za-z ]+)"),
        "gross": grab(r"Gross\s*[:\- ]\s*(\d+)"),
        "tare": grab(r"Tare\s*[:\- ]\s*(\d+)"),
        "date": grab(r"Date\s*[:\- ]\s*([0-9\-: ]+)"),
    }


def fetch_latest(limit=10):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        _, data = mail.search(None, '(SUBJECT "Weighment Slip")')
        ids = data[0].split()

        slips = []
        for msg_id in ids[-limit:]:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        text += part.get_payload(decode=True).decode("utf-8", errors="ignore")
            else:
                text += msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            slips.append(parse_rst(text))

        return slips
    except Exception as e:
        return [{"error": str(e)}]


# -----------------------------
# BOT UI
# -----------------------------
@dp.message(commands=["start"])
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.button(text="❓ Help", callback_data="help")
    kb.adjust(1)

    await message.answer("👋 Welcome Vinu!\nChoose an option:", reply_markup=kb.as_markup())


@dp.callback_query(lambda c: c.data == "latest")
async def cb_latest(query: types.CallbackQuery):
    slips = fetch_latest()

    msg = "📥 *Latest Weighment Slips*\n\n"
    for s in slips:
        msg += (
            f"• *RST:* {s['rst']}\n"
            f"  🚛 {s['vehicle']}\n"
            f"  🌾 {s['material']}\n"
            f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
            f"  🕒 Time: {s['date']}\n\n"
        )

    await query.message.edit_text(msg, parse_mode="Markdown")
    await query.answer()


@dp.callback_query(lambda c: c.data == "help")
async def cb_help(query: types.CallbackQuery):
    await query.message.edit_text(
        "❓ Help:\nClick Latest to view weighments.\n",
        parse_mode="Markdown"
    )
    await query.answer()


# -----------------------------
# MAIN
# -----------------------------
async def main():
    print("BOT RUNNING (aiogram, stable on Railway)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
