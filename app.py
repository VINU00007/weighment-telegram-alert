import os
import asyncio
import imaplib
import email
import fitz  # PyMuPDF
import easyocr
import numpy as np
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Load env variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

IMAP_HOST = "imap.gmail.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

reader = easyocr.Reader(["en"], gpu=False)


# --------------------------------------------------
# OCR extract from PDF
# --------------------------------------------------
def ocr_extract_text_from_pdf(path):
    text = ""
    doc = fitz.open(path)

    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8)
        img_np = img_np.reshape(pix.height, pix.width, pix.n)

        result = reader.readtext(img_np, detail=0, paragraph=True)
        text += "\n".join(result) + "\n"

    return text


# --------------------------------------------------
# Parse OCR text
# --------------------------------------------------
def parse_fields(text):
    def g(pattern):
        import re
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else "-"

    return {
        "rst": g(r"RST[:\- ]+(\d+)"),
        "vehicle": g(r"(TS|AP|CG|OD|MH)[0-9A-Z ]+"),
        "party": g(r"Party[:\- ]+([A-Za-z0-9 .]+)"),
        "place": g(r"Place[:\- ]+([A-Za-z0-9 .]+)"),
        "material": g(r"Material[:\- ]+([A-Za-z0-9 .]+)"),
        "gross": g(r"Gross[:\- ]+(\d+)"),
        "tare": g(r"Tare[:\- ]+(\d+)"),
    }


# --------------------------------------------------
# Download latest email PDF and extract text
# --------------------------------------------------
def fetch_latest_pdf():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        _, data = mail.search(None, '(SUBJECT "Weighment Slip")')
        ids = data[0].split()

        if not ids:
            return None, "NO_EMAIL"

        latest = ids[-1]
        _, msg_data = mail.fetch(latest, "(RFC822)")

        msg = email.message_from_bytes(msg_data[0][1])

        for part in msg.walk():
            if part.get_content_type() == "application/pdf":
                filename = "latest.pdf"
                path = f"/tmp/{filename}"
                open(path, "wb").write(part.get_payload(decode=True))
                return path, "OK"

        return None, "NO_PDF"

    except Exception as e:
        return None, f"ERR: {e}"


# --------------------------------------------------
# BOT UI
# --------------------------------------------------
@dp.message(CommandStart())
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Latest Weighment Slips", callback_data="latest")
    kb.adjust(1)

    await message.answer("👋 Hey Vinu!\nChoose an option:", reply_markup=kb.as_markup())


@dp.callback_query(lambda c: c.data == "latest")
async def latest_slips(query: types.CallbackQuery):
    pdf_path, status = fetch_latest_pdf()

    if status == "NO_EMAIL":
        await query.message.answer("⚠ No weighment slips found in email.")
        return

    if status == "NO_PDF":
        await query.message.answer("⚠ Email received but no PDF attached.")
        return

    if "ERR:" in status:
        await query.message.answer("⚠ Email error: " + status)
        return

    # Extract text from PDF
    text = ocr_extract_text_from_pdf(pdf_path)
    fields = parse_fields(text)

    msg = (
        "📥 *Latest Weighment Slip*\n\n"
        f"• *RST:* {fields['rst']}\n"
        f"🚛 *Vehicle:* {fields['vehicle']}\n"
        f"🏢 *Party:* {fields['party']}\n"
        f"📍 *Place:* {fields['place']}\n"
        f"🌾 *Material:* {fields['material']}\n"
        f"⚖ *Gross:* {fields['gross']} | *Tare:* {fields['tare']}\n"
    )

    await query.message.answer(msg, parse_mode="Markdown")


# --------------------------------------------------
# MAIN
# --------------------------------------------------
async def main():
    print("BOT RUNNING – PDF READER ACTIVE")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())