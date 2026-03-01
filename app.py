import asyncio
import imaplib
import email
from email.header import decode_header
import re

from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# -----------------------------
# CONFIG
# -----------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your-email@gmail.com"
IMAP_PASS = "your-app-password"

BOT_TOKEN = "8502486259:AAEI6w8aRyZHdElO82J_DmV9xGpdmMgjcZ0"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# -----------------------------
# PARSING
# -----------------------------
def parse_rst(text):
    def grab(pat):
        m = re.search(pat, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": grab(r"RST\s*[:\- ]\s*(\d+)"),
        "vehicle": grab(r"Vehicle\s*[:\- ]\s*([A-Z0-9\-]+)"),
        "material": grab(r"Material\s*[:\- ]\s*([A-Za-z0-9 \-]+)"),
        "gross": grab(r"Gross\s*[:\- ]\s*(\d+)"),
        "tare": grab(r"Tare\s*[:\- ]\s*(\d+)"),
        "date": grab(r"Date\s*[:\- ]\s*([0-9\-: ]+)")
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
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        text += payload.decode("utf-8", errors="ignore")

            slips.append(parse_rst(text))

        return slips

    except Exception as e:
        return [{"error": str(e)}]

# -----------------------------
# HANDLERS
# -----------------------------

@dp.message(CommandStart())
async def start(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.button(text="❓ Help", callback_data="help")
    kb.adjust(1)

    await message.answer(
        "👋 Welcome Vinu!\nChoose an option:",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(lambda q: q.data == "latest")
async def callback_latest(query: CallbackQuery):
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


@dp.callback_query(lambda q: q.data == "help")
async def callback_help(query: CallbackQuery):
    await query.message.edit_text(
        "❓ *HELP*\n\n"
        "• Tap *Latest Weighments* to see the newest slips.\n"
        "• Bot auto-fetches the last 10 weighment mails.\n",
        parse_mode="Markdown"
    )
    await query.answer()


# -----------------------------
# MAIN LOOP
# -----------------------------
async def main():
    print("BOT RUNNING → Aiogram 3.x stable on Railway")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
