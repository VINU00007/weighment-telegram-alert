import asyncio
import imaplib
import email
import os
import pdfplumber
from email.header import decode_header
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ======================================================
# CONFIG (from Railway environment variables)
# ======================================================
IMAP_HOST = "imap.gmail.com"
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ======================================================
# HELPERS
# ======================================================
def safe_decode(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


# ======================================================
# PDF PARSER
# ======================================================
def parse_pdf(filepath):
    try:
        with pdfplumber.open(filepath) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception as e:
        return {"error": f"PDF error: {e}"}

    def grab(pattern):
        import re
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": grab(r"RST[:\s]+(\d+)"),
        "vehicle": grab(r"Vehicle\s*No[:\s]+([A-Z0-9\-]+)"),
        "party": grab(r"Party\s*Name[:\s]+(.+)"),
        "place": grab(r"Place[:\s]+(.+)"),
        "material": grab(r"Material[:\s]+(.+)"),
        "gross": grab(r"Gross\s*Weight[:\s]+(\d+)"),
        "tare": grab(r"Tare\s*Weight[:\s]+(\d+)"),
        "date": grab(r"Date[:\s]+([0-9:A-Za-z\-\s]+)")
    }


# ======================================================
# EMAIL FETCHER (PDF ONLY)
# ======================================================
def fetch_latest_pdfs(limit=10):
    results = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        _, data = mail.search(None, '(SUBJECT "Weighment Slip")')
        ids = data[0].split()

        for msg_id in ids[-limit:]:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            for part in msg.walk():
                if part.get_content_type() == "application/pdf":
                    filename = safe_decode(part.get_filename())

                    filepath = f"/tmp/{filename}"
                    with open(filepath, "wb") as f:
                        f.write(part.get_payload(decode=True))

                    parsed = parse_pdf(filepath)
                    results.append(parsed)

        return results

    except Exception as e:
        return [{"error": f"IMAP error: {e}"}]


# ======================================================
# BOT UI HANDLERS
# ======================================================
@dp.message(CommandStart())
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.button(text="❓ Help", callback_data="help")
    kb.adjust(1)

    await message.answer("👋 Welcome Vinu! Choose an option:", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "latest")
async def latest_callback(query: types.CallbackQuery):
    slips = fetch_latest_pdfs()

    msg = "📥 *Latest Weighment Slips*\n\n"

    for s in slips:
        if "error" in s:
            msg += f"⚠ Error: {s['error']}\n\n"
            continue

        msg += (
            f"• *RST:* {s['rst']}\n"
            f"  🚛 Vehicle: {s['vehicle']}\n"
            f"  🏭 Party: {s['party']}\n"
            f"  📍 Place: {s['place']}\n"
            f"  🌾 Material: {s['material']}\n"
            f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
            f"  🕒 Time: {s['date']}\n\n"
        )

    await query.message.edit_text(msg, parse_mode="Markdown")
    await query.answer()


@dp.callback_query(F.data == "help")
async def help_callback(query: types.CallbackQuery):
    await query.message.edit_text(
        "❓ *Help Menu*\n"
        "This bot reads weighment PDF slips from Gmail inbox and shows them here.",
        parse_mode="Markdown"
    )
    await query.answer()


# ======================================================
# MAIN
# ======================================================
async def main():
    print("BOT RUNNING → Aiogram 3.x + PDF Parser + Railway Stable")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
