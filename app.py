import asyncio
import imaplib
import email
from email.header import decode_header
import re

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = "your-email@gmail.com"
IMAP_PASS = "your-app-password"

BOT_TOKEN = "8502486259:AAEI6w8aRyZHdElO82J_DmV9xGpdmMgjcZ0"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------------------------------------------------
# PARSER — FIXED FOR YOUR SLIPS
# ---------------------------------------------------------
def parse_rst(text):
    def grab(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": grab(r"RST\s*[:\-]\s*(\d+)"),
        "vehicle": grab(r"Vehicle\s*No\s*[:\-]\s*([A-Z0-9]+)"),
        "party": grab(r"PARTY\s*NAME\s*[:\-]\s*(.+)"),
        "place": grab(r"PLACE\s*[:\-]\s*([A-Za-z0-9]+)"),
        "material": grab(r"MATERIAL\s*[:\-]\s*([A-Za-z ]+)"),
        "gross": grab(r"Gross\s*[:\-]\s*(\d+)\s*Kgs"),
        "tare": grab(r"Tare\s*[:\-]\s*(\d+)\s*Kgs"),
        "date": grab(r"(\d{1,2}-[A-Za-z]{3}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"),
    }

# ---------------------------------------------------------
# EMAIL READER
# ---------------------------------------------------------
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
                        try:
                            text += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except:
                            pass
            else:
                try:
                    text += msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                except:
                    pass

            slips.append(parse_rst(text))

        return slips
    except Exception as e:
        return [{"error": str(e)}]

# ---------------------------------------------------------
# BOT UI HANDLERS
# ---------------------------------------------------------
@dp.message(CommandStart())
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.button(text="❓ Help", callback_data="help")
    kb.adjust(1)

    await message.answer("👋 Welcome Vinu!\nChoose an option:", reply_markup=kb.as_markup())


@dp.callback_query(lambda c: c.data == "latest")
async def callback_latest(query: types.CallbackQuery):
    slips = fetch_latest()

    msg = "📥 *Latest Weighment Slips*\n\n"

    for s in slips:
        if "error" in s:
            msg += f"⚠ Error: {s['error']}\n\n"
            continue

        msg += (
            f"• RST: {s['rst']}\n"
            f"  🚛 Vehicle: {s['vehicle']}\n"
            f"  🏢 Party: {s['party']}\n"
            f"  📍 Place: {s['place']}\n"
            f"  🌾 Material: {s['material']}\n"
            f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
            f"  🕒 Time: {s['date']}\n\n"
        )

    await query.message.edit_text(msg, parse_mode="Markdown")
    await query.answer()


@dp.callback_query(lambda c: c.data == "help")
async def callback_help(query: types.CallbackQuery):
    await query.message.edit_text(
        "❓ *Help*\n\nClick *Latest Weighments* to view the newest slips.\n",
        parse_mode="Markdown",
    )
    await query.answer()

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
async def main():
    print("BOT RUNNING → Aiogram 3.x stable on Railway")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
