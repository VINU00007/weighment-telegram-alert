# ---------------------------------------------------------
#  WEIGHBRIDGE TELEGRAM BOT - FINAL PRODUCTION VERSION
#  Author: ChatGPT for Vinu
# ---------------------------------------------------------

import os
import re
import json
import time
import asyncio
import requests
import imaplib
import email
from datetime import datetime, timedelta
from email.header import decode_header
from io import BytesIO
import pdfplumber

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------
# ENV VARIABLES
# ---------------------------------------------------------

IMAP_SERVER = "imap.gmail.com"
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")     # Normal group (NOT -100 prefix)

DATA_FILE = "yard_data.json"
SENT_FILE = "sent_alerts.json"


# ---------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------

def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def fmt(dt):
    if not dt:
        return "N/A"
    return dt.strftime("%d-%b-%y | %I:%M %p")


def yard_duration(t1, t2):
    if not t1 or not t2:
        return "N/A"
    delta = t2 - t1
    mins = int(delta.total_seconds() // 60)
    h = mins // 60
    m = mins % 60
    return f"{h}h {m}m"


# ---------------------------------------------------------
# FILE HELPERS (JSON LOAD/SAVE)
# ---------------------------------------------------------

def load_json(file, default):
    if not os.path.exists(file):
        return default
    try:
        return json.load(open(file))
    except:
        return default


def save_json(file, data):
    json.dump(data, open(file, "w"), indent=2, default=str)


# ---------------------------------------------------------
# TELEGRAM SEND
# ---------------------------------------------------------

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram send failed:", e)


# ---------------------------------------------------------
# TEXT HELPERS
# ---------------------------------------------------------

def safe_decode(val):
    if not val:
        return ""
    parts = decode_header(val)
    out = []
    for p, enc in parts:
        if isinstance(p, bytes):
            out.append(p.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(p)
    return "".join(out)


def pick(text, pattern):
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def normalize(s):
    return re.sub(r"\s+", " ", s.strip()) if s else ""


# ---------------------------------------------------------
# PDF PARSER
# ---------------------------------------------------------

def parse_dt(s):
    if not s:
        return None
    fmts = [
        "%d-%b-%y %I:%M:%S %p",
        "%d-%b-%Y %I:%M:%S %p",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None


def extract_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        print("PDF read error")
        return None

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    material = pick(text, r"MATERIAL\s*:\s*(.+?)\s+(?:CELL|NO|$)")
    material = material.replace("CELL", "").replace("NO", "")
    material = normalize(material)

    data = {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)"),
        "Material": material,
        "GrossKg": pick(text, r"Gross\.?:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.?:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross.*?Kgs.*?" + dt_pat),
        "TareDT": pick(text, r"Tare.*?Kgs.*?" + dt_pat),
    }

    return data


# ---------------------------------------------------------
# BACKGROUND SCANNER — RUNS EVERY 30 SEC
# ---------------------------------------------------------

async def background_scanner():
    await asyncio.sleep(5)  # Wait for bot to start

    while True:
        try:
            print("[SCAN] Checking emails...")

            yard = load_json(DATA_FILE, {})
            sent = load_json(SENT_FILE, {"entry": [], "complete": []})

            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
            mail.login(EMAIL_USER, EMAIL_PASS)
            mail.select("inbox")

            _, data = mail.uid("search", None, "ALL")
            uids = [int(x) for x in data[0].split()]
            recent = uids[-200:]

            for uid in recent:
                _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = safe_decode(msg.get("Subject")).upper()
                if "WEIGH" not in subject and "SLIP" not in subject:
                    continue

                for part in msg.walk():
                    if "pdf" in part.get_content_type():
                        pdf_bytes = part.get_payload(decode=True)
                        info = extract_pdf(pdf_bytes)
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
                                "GrossTime": None,
                                "Tare": None,
                                "TareTime": None,
                            }

                        if info["GrossKg"]:
                            yard[rst]["Gross"] = int(info["GrossKg"])
                            yard[rst]["GrossTime"] = parse_dt(info["GrossDT"])

                        if info["TareKg"]:
                            yard[rst]["Tare"] = int(info["TareKg"])
                            yard[rst]["TareTime"] = parse_dt(info["TareDT"])

                        # -------- ENTRY ALERT --------
                        if (
                            (yard[rst]["Gross"] and not yard[rst]["Tare"])
                            or (yard[rst]["Tare"] and not yard[rst]["Gross"])
                        ) and rst not in sent["entry"]:

                            wt = yard[rst]["Gross"] or yard[rst]["Tare"]
                            t = yard[rst]["GrossTime"] or yard[rst]["TareTime"]
                            typ = "Gross" if yard[rst]["Gross"] else "Tare"

                            msg_txt = (
                                f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                                f"🧾 RST : {rst}   🚛 {yard[rst]['Vehicle']}\n"
                                f"🏭 PARTY : {yard[rst]['Party']}\n"
                                f"🌾 MATERIAL : {yard[rst]['Material']}\n\n"
                                f"《 FIRST WEIGHMENT 》\n"
                                f"⚖ {typ} : {wt} Kg\n"
                                f"🕒 {fmt(t)}\n\n"
                                f"《 SECOND WEIGHMENT 》 Pending\n"
                                f"🟡 STATUS : VEHICLE INSIDE YARD"
                            )
                            send_telegram(msg_txt)
                            sent["entry"].append(rst)

                        # -------- COMPLETION ALERT --------
                        if (
                            yard[rst]["Gross"]
                            and yard[rst]["Tare"]
                            and rst not in sent["complete"]
                        ):
                            t1 = yard[rst]["GrossTime"]
                            t2 = yard[rst]["TareTime"]
                            times = sorted([t for t in [t1, t2] if t])

                            if len(times) >= 2:
                                in_time = times[0]
                                out_time = times[1]
                                net = abs(
                                    yard[rst]["Gross"] - yard[rst]["Tare"]
                                )

                                msg_txt = (
                                    f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                                    f"🧾 RST : {rst}   🚛 {yard[rst]['Vehicle']}\n"
                                    f"🏭 PARTY : {yard[rst]['Party']}\n"
                                    f"🌾 MATERIAL : {yard[rst]['Material']}\n\n"
                                    f"⟪ IN  ⟫ {fmt(in_time)}\n"
                                    f"⟪ OUT ⟫ {fmt(out_time)}\n"
                                    f"⏳ YARD TIME : {yard_duration(in_time, out_time)}\n\n"
                                    f"🔵 NET LOAD : {net} Kg\n"
                                    f"🟢 STATUS : COMPLETED"
                                )

                                send_telegram(msg_txt)
                                sent["complete"].append(rst)

            mail.logout()

            save_json(DATA_FILE, yard)
            save_json(SENT_FILE, sent)

            print("[SCAN] Done.")

        except Exception as e:
            print("Scanner error:", e)

        await asyncio.sleep(30)


# ---------------------------------------------------------
# TELEGRAM BOT HANDLERS
# ---------------------------------------------------------

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 Latest Weighments", callback_data="latest"),
            InlineKeyboardButton("📊 Completed Today", callback_data="completed"),
        ],
        [
            InlineKeyboardButton("🏭 Vehicles Inside", callback_data="inside"),
            InlineKeyboardButton("🔍 Search RST", callback_data="search_rst"),
        ],
        [
            InlineKeyboardButton("🔄 24h Summary", callback_data="summary"),
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome Vinu! Choose an option:",
        reply_markup=main_keyboard()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Help Menu:",
        reply_markup=main_keyboard()
    )


# ---------------------------------------------------------
# CALLBACK HANDLER
# ---------------------------------------------------------

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    yard = load_json(DATA_FILE, {})

    # ---------- LATEST ----------
    if data == "latest":
        await query.edit_message_text("⏳ Fetching latest...")

        latest = sorted(
            yard.values(),
            key=lambda x: int(x["RST"]),
            reverse=True
        )[:5]

        msg = "📥 Latest Weighment Slips:\n\n"
        for d in latest:
            msg += (
                f"📌 RST {d['RST']}\n"
                f"🚛 {d['Vehicle']}\n"
                f"🏭 {d['Party']}\n"
                f"🌾 {d['Material']}\n"
                f"⚖ Gross: {d['Gross'] or '-'} | Tare: {d['Tare'] or '-'}\n\n"
            )

        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        return

    # ---------- COMPLETED TODAY ----------
    if data == "completed":
        await query.edit_message_text("⏳ Checking completed...")

        now = now_ist()
        start = now.replace(hour=0, minute=0, second=0)

        msg = "📊 Completed Today:\n\n"

        found = False
        for d in yard.values():
            if d["Gross"] and d["Tare"]:
                t1 = d["GrossTime"]
                t2 = d["TareTime"]
                if not t1 or not t2:
                    continue
                out = max(t1, t2)
                if out >= start:
                    found = True
                    msg += (
                        f"RST {d['RST']} | {d['Vehicle']} | NET {abs(d['Gross'] - d['Tare'])} Kg\n"
                    )

        if not found:
            msg += "No completed weighments today."

        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        return

    # ---------- INSIDE YARD ----------
    if data == "inside":
        await query.edit_message_text("⏳ Checking inside yard...")

        msg = "🏭 Vehicles Inside Yard:\n\n"
        found = False

        for d in yard.values():
            if (d["Gross"] and not d["Tare"]) or (d["Tare"] and not d["Gross"]):
                found = True
                t = d["GrossTime"] or d["TareTime"]
                pending = "Tare" if d["Gross"] else "Gross"
                msg += (
                    f"RST {d['RST']} | {d['Vehicle']}\n"
                    f"IN {fmt(t)} | Pending {pending}\n\n"
                )

        if not found:
            msg += "Yard is clear."

        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        return

    # ---------- SEARCH RST ----------
    if data == "search_rst":
        await query.edit_message_text("🔍 Send RST number:")
        context.user_data["await_rst"] = True
        return

    # ---------- SUMMARY ----------
    if data == "summary":
        await query.edit_message_text("⏳ Generating 24h summary...")

        now = now_ist()
        start = now - timedelta(hours=24)

        msg = "🔄 24-Hour Yard Summary:\n\n"
        found = False

        for d in yard.values():
            if d["Gross"] and d["Tare"]:
                t1 = d["GrossTime"]
                t2 = d["TareTime"]
                out = max(t1, t2)
                if out >= start:
                    found = True
                    msg += (
                        f"{d['RST']} | {d['Vehicle']} | {d['Material']}\n"
                        f"IN {fmt(min(t1, t2))} | OUT {fmt(out)}\n"
                        f"NET {abs(d['Gross'] - d['Tare'])} Kg\n\n"
                    )

        if not found:
            msg += "No weighments in last 24 hours."

        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        return

    # ---------- HELP ----------
    if data == "help":
        await query.edit_message_text("ℹ️ Help menu:", reply_markup=main_keyboard())
        return


# ---------------------------------------------------------
# HANDLE "SEND RST NUMBER"
# ---------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    yard = load_json(DATA_FILE, {})

    # User is searching RST
    if context.user_data.get("await_rst"):
        context.user_data["await_rst"] = False

        rst = update.message.text.strip()
        if rst not in yard:
            await update.message.reply_text("❌ RST not found.", reply_markup=main_keyboard())
            return

        d = yard[rst]

        msg = (
            f"📌 RST {rst}\n"
            f"🚛 {d['Vehicle']}\n"
            f"🏭 {d['Party']}\n"
            f"🌾 {d['Material']}\n\n"
        )

        t1 = d["GrossTime"]
        t2 = d["TareTime"]
        gross = d["Gross"]
        tare = d["Tare"]

        # First weighment
        if gross and not tare:
            msg += (
                f"⟪ FIRST ⟫ Gross: {gross} Kg\n"
                f"🕒 {fmt(t1)}\n"
                f"Pending Tare\n"
            )
        elif tare and not gross:
            msg += (
                f"⟪ FIRST ⟫ Tare: {tare} Kg\n"
                f"🕒 {fmt(t2)}\n"
                f"Pending Gross\n"
            )
        elif gross and tare:
            times = sorted([t1, t2])
            msg += (
                f"⟪ IN  ⟫ {fmt(times[0])}\n"
                f"⟪ OUT ⟫ {fmt(times[1])}\n"
                f"🔵 NET : {abs(gross - tare)} Kg\n"
                f"⏳ YARD TIME : {yard_duration(times[0], times[1])}\n"
            )

        await update.message.reply_text(msg, reply_markup=main_keyboard())
        return


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Start scanner
    asyncio.create_task(background_scanner())

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("BOT RUNNING...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())