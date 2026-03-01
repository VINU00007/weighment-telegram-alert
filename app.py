import asyncio
import imaplib
import email
from email.header import decode_header
import re

from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# -----------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your-email@gmail.com"       # <-- your mail
IMAP_PASS = "your-app-password"          # <-- Gmail App password

BOT_TOKEN = "8502486259:AAEI6w8aRyZHdElO82J_DmV9xGpdmMgjcZ0"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# -----------------------------------------------------
# EMAIL PARSING
# -----------------------------------------------------
def parse_rst(text: str):
    """Extract fields safely from text."""
    def grab(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": grab(r"RST\s*[:\- ]\s*(\d+)"),
        "vehicle": grab(r"Vehicle\s*[:\- ]\s*([A-Za-z0-9\- ]+)"),
        "material": grab(r"Material\s*[:\- ]\s*([A-Za-z0-9 \-]+)"),
        "gross": grab(r"Gross\s*[:\- ]\s*(\d+)"),
        "tare": grab(r"Tare\s*[:\- ]\s*(\d+)"),
        "date": grab(r"(?:Date|Time)\s*[:\- ]\s*([0-9\-: ]+)")
    }


def fetch_latest(limit=10):
    """Read last N weighment emails safely."""
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

            # extract text/plain content
            text = ""
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        text += payload.decode("utf-8", errors="ignore")

            info = parse_rst(text)

            # skip invalid mails with no RST
            if info.get("rst", "-") != "-":
                slips.append(info)

        return slips

    except Exception as e:
        return [{"error": str(e)}]


# -----------------------------------------------------
# BOT UI AND HANDLERS
# -----------------------------------------------------
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
        rst = s.get("rst", "-")
        veh = s.get("vehicle", "-")
        mat = s.get("material", "-")
        gr = s.get("gross", "-")
        ta = s.get("tare", "-")
        dt = s.get("date", "-")

        msg += (
            f"• *RST:* {rst}\n"
            f"  🚛 {veh}\n"
            f"  🌾 {mat}\n"
            f"  ⚖ Gross: {gr} | Tare: {ta}\n"
            f"  🕒 Time: {dt}\n\n"
        )

    await query.message.edit_text(msg, parse_mode="Markdown")
    await query.answer()


@dp.callback_query(lambda q: q.data == "help")
async def callback_help(query: CallbackQuery):
    await query.message.edit_text(
        "❓ *HELP*\n\n"
        "• Tap *Latest Weighments* to see the newest slips.\n"
        "• Bot auto-reads last 10 mails containing \"Weighment Slip\".\n"
        "• Faulty or incomplete mails are safely ignored.\n",
        parse_mode="Markdown"
    )
    await query.answer()


# -----------------------------------------------------
# MAIN LOOP
# -----------------------------------------------------
async def main():
    print("BOT RUNNING → Aiogram 3.x stable on Railway")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
