import asyncio
import imaplib
import email
import os
import re
from email.header import decode_header
from aiogram import Bot, Dispatcher, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PyPDF2 import PdfReader

# -----------------------------
# CONFIG
# -----------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# -----------------------------
# PARSE PDF TEXT
# -----------------------------
def parse_pdf_text(text):
    def grab(pat):
        m = re.search(pat, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": grab(r"RST[:\s]+(\d+)"),
        "vehicle": grab(r"Vehicle\s*No[:\s]+([A-Z0-9]+)"),
        "party": grab(r"Party\s*Name[:\s]+(.+)"),
        "place": grab(r"Place[:\s]+(.+)"),
        "material": grab(r"Material[:\s]+(.+)"),
        "gross": grab(r"Gross\s*Weight[:\s]+(\d+)"),
        "tare": grab(r"Tare\s*Weight[:\s]+(\d+)"),
        "date": grab(r"Date[:\s]+([0-9\-: AMPamp]+)"),
    }


# -----------------------------
# FETCH + READ PDF ATTACHMENTS
# -----------------------------
def fetch_latest_pdfs(limit=10):
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

            # find PDF attachment
            for part in msg.walk():
                if part.get_content_maintype() == "application" and part.get_filename():
                    filename = part.get_filename()
                    file_data = part.get_payload(decode=True)

                    # Save temp PDF
                    path = f"/tmp/{filename}"
                    with open(path, "wb") as f:
                        f.write(file_data)

                    # Extract PDF text
                    reader = PdfReader(path)
                    full_text = ""
                    for page in reader.pages:
                        full_text += page.extract_text() + "\n"

                    # Parse
                    slips.append(parse_pdf_text(full_text))

        return slips

    except Exception as e:
        return [{"error": str(e)}]


# -----------------------------
# BOT COMMANDS
# -----------------------------
@dp.message(F.text == "/start")
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighments", callback_data="latest")
    kb.button(text="❓ Help", callback_data="help")
    kb.adjust(1)

    await message.answer("👋 Welcome Vinu! Choose an option:", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "latest")
async def callback_latest(query: types.CallbackQuery):
    slips = fetch_latest_pdfs()

    if not slips:
        await query.message.edit_text("❌ No weighment PDFs found.")
        return

    msg = "📥 *Latest Weighment Slips*\n\n"

    for s in slips:
        msg += (
            f"• *RST:* {s['rst']}\n"
            f"  🚛 Vehicle: {s['vehicle']}\n"
            f"  🏢 Party: {s['party']}\n"
            f"  📍 Place: {s['place']}\n"
            f"  🌾 Material: {s['material']}\n"
            f"  ⚖ Gross: {s['gross']} | Tare: {s['tare']}\n"
            f"  🕒 Time: {s['date']}\n\n"
        )

    await query.message.edit_text(msg, parse_mode="Markdown")
    await query.answer()


@dp.callback_query(F.data == "help")
async def callback_help(query: types.CallbackQuery):
    await query.message.edit_text(
        "❓ *Help*\n"
        "This bot shows the latest weighment slips from your inbox PDF attachments.",
        parse_mode="Markdown"
    )
    await query.answer()


# -----------------------------
# RUN BOT
# -----------------------------
async def main():
    print("BOT RUNNING → Aiogram 3.x stable on Railway")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
