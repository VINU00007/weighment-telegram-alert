import imaplib
import email
from email.header import decode_header
import os
import time
import re
import pdfplumber
from io import BytesIO
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================================
# ENV VARS
# =========================================
IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN")
CHAT_ID    = int(os.getenv("CHAT_ID"))

# =========================================
# TIME HELPERS
# =========================================
def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def f12(dt):
    if not dt:
        return "—"
    return dt.strftime("%d-%b %I:%M %p")

# =========================================
# TEXT PARSING HELPERS
# =========================================
def safe_decode(v):
    if not v:
        return ""
    parts = decode_header(v)
    out = []
    for p, enc in parts:
        if isinstance(p, bytes):
            out.append(p.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(p)
    return "".join(out)

def pick(text, pattern):
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""

# =========================================
# PDF PARSE
# =========================================
def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        return {}

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)"),
        "Material": pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL"),
        "Gross": pick(text, r"Gross.*?:\s*(\d+)"),
        "Tare": pick(text, r"Tare.*?:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross.*?Kgs.*?" + dt_pat),
        "TareDT": pick(text, r"Tare.*?Kgs.*?" + dt_pat)
    }

def parse_dt(s):
    if not s:
        return None
    for f in ["%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"]:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None

# =========================================
# SCAN EMAIL
# =========================================
def scan_mails(limit=200):
    yard = {}

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    _, data = mail.uid("search", None, "ALL")
    uids = [int(x) for x in data[0].split()]
    selected = uids[-limit:]

    for uid in selected:
        _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        sub = safe_decode(msg.get("Subject")).upper()
        if "WEIGH" not in sub and "SLIP" not in sub:
            continue

        for part in msg.walk():
            if "pdf" in part.get_content_type():
                pdf_bytes = part.get_payload(decode=True)
                info = extract_from_pdf(pdf_bytes)
                if not info or not info.get("RST"):
                    continue

                rst = info["RST"]
                if rst not in yard:
                    yard[rst] = {
                        "RST": rst,
                        "Vehicle": info["Vehicle"],
                        "Party": info["Party"],
                        "Material": info["Material"],
                        "Gross": None,
                        "GrossDT": None,
                        "Tare": None,
                        "TareDT": None
                    }

                if info["Gross"]:
                    yard[rst]["Gross"] = int(info["Gross"])
                    yard[rst]["GrossDT"] = parse_dt(info["GrossDT"])

                if info["Tare"]:
                    yard[rst]["Tare"] = int(info["Tare"])
                    yard[rst]["TareDT"] = parse_dt(info["TareDT"])

    mail.logout()
    return yard

# =========================================
# MESSAGE GENERATORS
# =========================================
def full_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 Latest Weighments", callback_data="latest"),
            InlineKeyboardButton("📊 Completed Today", callback_data="completed")
        ],
        [
            InlineKeyboardButton("🏭 Vehicles Inside", callback_data="inside"),
            InlineKeyboardButton("🔍 Search RST", callback_data="search_rst")
        ],
        [
            InlineKeyboardButton("🔄 Yard Summary (24h)", callback_data="summary")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ])

# =========================================
# BOT COMMANDS
# =========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome Vinu!\nChoose an option below:",
        reply_markup=full_menu()
    )

async def help_btn(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(
        "ℹ️ Choose any option:",
        reply_markup=full_menu()
    )

# =========================================
# CALLBACK HANDLERS
# =========================================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # prevents timeout

    data = query.data
    yard = scan_mails()

    # --------------------------------------
    # LATEST
    # --------------------------------------
    if data == "latest":
        msg = "📥 *Latest Weighment Slips Found:*\n\n"
        for rst, d in list(yard.items())[-5:][::-1]:
            msg += (
                f"📌 RST {rst}\n"
                f"🚛 {d['Vehicle']}\n"
                f"🌾 {d['Material']}\n"
                f"⚖ Gross: {d['Gross'] or '—'} | Tare: {d['Tare'] or '—'}\n\n"
            )
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=full_menu())
        return

    # --------------------------------------
    # COMPLETED
    # --------------------------------------
    if data == "completed":
        msg = "📊 *Completed Today*\n\n"
        today = now_ist().date()
        for rst, d in yard.items():
            if d["Gross"] and d["Tare"]:
                t1 = d["GrossDT"] or d["TareDT"]
                if t1 and t1.date() == today:
                    net = abs(d["Gross"] - d["Tare"])
                    msg += (
                        f"RST {rst} | {d['Vehicle']} | NET {net} Kg\n"
                    )
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=full_menu())
        return

    # --------------------------------------
    # INSIDE
    # --------------------------------------
    if data == "inside":
        msg = "🏭 *Vehicles Inside Yard*\n\n"
        for rst, d in yard.items():
            if (d["Gross"] and not d["Tare"]) or (d["Tare"] and not d["Gross"]):
                msg += f"RST {rst} – {d['Vehicle']} – {d['Material']}\n"
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=full_menu())
        return

    # --------------------------------------
    # SUMMARY (24h)
    # --------------------------------------
    if data == "summary":
        msg = "🔄 *24-Hour Yard Summary*\n\n"
        cutoff = now_ist() - timedelta(hours=24)
        for rst, d in yard.items():
            tmax = d["GrossDT"] or d["TareDT"]
            if tmax and tmax >= cutoff:
                msg += f"{rst} | {d['Vehicle']} | {d['Material']}\n"
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=full_menu())
        return

    # --------------------------------------
    # SEARCH RST
    # --------------------------------------
    if data == "search_rst":
        context.user_data["mode"] = "search"
        await query.message.reply_text("🔍 Send the *RST Number*:")
        return

# =========================================
# TEXT INPUT HANDLER (search)
# =========================================
async def text_handler(update: Update, context):
    if context.user_data.get("mode") == "search":
        rst = update.message.text.strip()
        yard = scan_mails()
        if rst not in yard:
            await update.message.reply_text("❌ RST not found.", reply_markup=full_menu())
        else:
            d = yard[rst]

            # yard duration
            t1 = d["GrossDT"] or d["TareDT"]
            t2 = d["TareDT"] if d["GrossDT"] else d["GrossDT"]
            duration = ""
            if t1 and t2:
                diff = t2 - t1
                duration = f"{diff.seconds//3600}h {(diff.seconds//60)%60}m"

            msg = (
                f"📌 *RST {rst}*\n"
                f"🚛 {d['Vehicle']}\n"
                f"🌾 {d['Material']}\n\n"
                f"Gross: {d['Gross'] or '—'} ({f12(d['GrossDT'])})\n"
                f"Tare: {d['Tare'] or '—'} ({f12(d['TareDT'])})\n\n"
                f"⏱ Yard Time: {duration or '—'}"
            )

            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=full_menu())

        context.user_data["mode"] = None
        return

# =========================================
# MAIN
# =========================================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler := CommandHandler("help", help_btn))
    app.add_handler(CallbackQueryHandler(help_btn, pattern="help"))
    app.add_handler(CommandHandler("help", help_btn))
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("BOT RUNNING...")
    app.run_polling()