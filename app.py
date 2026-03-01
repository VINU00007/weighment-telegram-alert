import asyncio
import email
import imaplib
import os
import re
import io
import PyPDF2
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ----------------------------
# ENV VARIABLES
# ----------------------------
IMAP_USER = os.getenv("EMAIL_USER")
IMAP_PASS = os.getenv("EMAIL_PASS")
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ----------------------------
# PDF PARSER
# ----------------------------
def extract_field(text, label):
    try:
        pattern = rf"{label}\s*[:\- ]\s*([A-Za-z0-9 \/]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"
    except:
        return "-"


def extract_pdf_text(msg):
    """Return text from attached PDF file."""
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
            except:
                return None
    return None


# ----------------------------
# FETCH LATEST PDF SLIPS
# ----------------------------
def fetch_latest(limit=10):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        # Search ALL emails (no subject filter)
        _, data = mail.search(None, "ALL")
        ids = data[0].split()

        slips = []

        for msg_id in ids[::-1][:limit]:  # reverse for latest first
            _, raw = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])

            pdf_text = extract_pdf_text(msg)
            if not pdf_text:
                continue

            slip = {
                "rst": extract_field(pdf_text, "RST"),
                "vehicle": extract_field(pdf_text, "Vehicle"),
                "party": extract_field(pdf_text, "Party"),
                "place": extract_field(pdf_text, "Place"),
                "material": extract_field(pdf_text, "Material"),
                "gross": extract_field(pdf_text, "Gross"),
                "tare": extract_field(pdf_text, "Tare"),
                "time": extract_field(pdf_text, "Date"),
            }

            slips.append(slip)

        return slips

    except Exception as e:
        return [{"error": f"IMAP error: {str(e)}"}]


# ----------------------------
# BOT UI
# ----------------------------
@dp.message(CommandStart())
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.adjust(1)

    await message.answer(
        "👋 Welcome Vinu!\nTap below to view latest weighment slips:",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(lambda c: c.data == "latest")
async def latest_slips(query: types.CallbackQuery):
    slips = fetch_latest()

    if not slips:
        await query.message.edit_text("⚠ No weighment slips found.")
        return

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


# ----------------------------
# START BOT
# ----------------------------
async def main():
    print("BOT RUNNING — PDF READER ACTIVE")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())