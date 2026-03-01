import asyncio
import email
import imaplib
import os
import re
from email.header import decode_header
import PyPDF2
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# -------------------------------------------------------------------
# ENVIRONMENT VARIABLES (Railway)
# -------------------------------------------------------------------
IMAP_USER = os.getenv("EMAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")    # unused now but keep for future

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# -------------------------------------------------------------------
# PDF PARSER HELPERS
# -------------------------------------------------------------------
def parse_field(text, label):
    """Extract field from PDF text."""
    try:
        # Example: RST No: 139
        pattern = rf"{label}\s*[:\- ]\s*([A-Za-z0-9 \/]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else "-"
    except:
        return "-"


def extract_pdf_text(msg):
    """Extract text from attached PDF."""
    for part in msg.walk():
        if part.get_content_type() == "application/pdf":
            pdf_bytes = part.get_payload(decode=True)
            if not pdf_bytes:
                continue

            try:
                reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
            except Exception as e:
                return None
    return None


# -------------------------------------------------------------------
# FETCH LATEST PDF WEIGHMENT SLIPS
# -------------------------------------------------------------------
def fetch_latest(limit=10):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        _, data = mail.search(None, '(SUBJECT "Weighment Slip")')
        ids = data[0].split()

        slips = []

        for msg_id in ids[-limit:]:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            pdf_text = extract_pdf_text(msg)
            if not pdf_text:
                continue

            slip = {
                "rst": parse_field(pdf_text, "RST"),
                "vehicle": parse_field(pdf_text, "Vehicle"),
                "party": parse_field(pdf_text, "Party"),
                "place": parse_field(pdf_text, "Place"),
                "material": parse_field(pdf_text, "Material"),
                "gross": parse_field(pdf_text, "Gross"),
                "tare": parse_field(pdf_text, "Tare"),
                "time": parse_field(pdf_text, "Date"),
            }
            slips.append(slip)

        return slips

    except Exception as e:
        return [{"error": f"IMAP error: {str(e)}"}]


# -------------------------------------------------------------------
# TELEGRAM BOT UI
# -------------------------------------------------------------------
@dp.message(CommandStart())
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.button(text="❓ Help", callback_data="help")
    kb.adjust(1)

    await message.answer(
        "👋 Welcome Vinu!\nChoose an option:",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(lambda c: c.data == "latest")
async def callback_latest(query: types.CallbackQuery):
    slips = fetch_latest()

    if not slips:
        await query.message.edit_text("⚠ No weighment slips found.")
        return

    # If IMAP returned an error
    if "error" in slips[0]:
        await query.message.edit_text(f"⚠ Error: {slips[0]['error']}")
        return

    text = "📥 *Latest Weighment Slips*\n\n"

    for s in slips:
        text += (
            f"• RST: {s['rst']}\n"
            f"  🚛 Vehicle: {s['vehicle']}\n"
            f"  🏢 Party: {s['party']}\n"
            f"  📍 Place: {s['place']}\n"
            f"  🌾 Material: {s['material']}\n"
            f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
            f"  🕒 Time: {s['time']}\n\n"
        )

    await query.message.edit_text(text, parse_mode="Markdown")
    await query.answer()


@dp.callback_query(lambda c: c.data == "help")
async def callback_help(query: types.CallbackQuery):
    await query.message.edit_text(
        "❓ *Help*\n"
        "Use *Latest Weighments* to view the most recent weighment slips.",
        parse_mode="Markdown"
    )
    await query.answer()


# -------------------------------------------------------------------
# START BOT
# -------------------------------------------------------------------
async def main():
    print("BOT RUNNING → Aiogram 3.x stable on Railway")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
