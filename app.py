import imaplib
import email
from email.header import decode_header
import os
import requests
import time
import re
import json
from datetime import datetime, timedelta
from io import BytesIO
import pdfplumber

IMAP_SERVER = "imap.gmail.com"

# Load env vars
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Storage files
COMPLETED_FILE = "completed_records.json"
PENDING_FILE = "pending_records.json"
PROCESSED_FILE = "processed.json"


def now_ist():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def format_12h(dt):
    if not dt:
        return "NA"
    return dt.strftime("%I:%M %p")


def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass


def safe_decode(v):
    if not v:
        return ""
    parts = decode_header(v)
    out = []
    for p, enc in parts:
        out.append(p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p)
    return "".join(out)


def pick(text, pattern):
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def normalize(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_dt(s):
    if not s:
        return None
    fmts = ["%d-%b-%y %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p"]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except:
            pass
    return None


def load_json(f):
    if not os.path.exists(f):
        return []
    try:
        return json.load(open(f))
    except:
        return []


def save_json(f, data):
    with open(f, "w") as file:
        json.dump(data, file, indent=2)


# ============= PDF Extraction =============

def extract_from_pdf(pdf_bytes):
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""

    dt_pat = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)"

    party = pick(text, r"PARTY\s*NAME\s*[:\-]?\s*([A-Za-z0-9 &\.\-]+)")

    return {
        "RST": pick(text, r"RST\s*:\s*(\d+)"),
        "Vehicle": pick(text, r"Vehicle No\s*:\s*([A-Z0-9\- ]+)"),
        "Party": party,
        "Material": normalize(pick(text, r"MATERIAL\s*:\s*(.+?)\s+CELL")),
        "GrossKg": pick(text, r"Gross\.\s*:\s*(\d+)"),
        "TareKg": pick(text, r"Tare\.\s*:\s*(\d+)"),
        "GrossDT": pick(text, r"Gross\.\s*:\s*\d+\s*Kgs\s*" + dt_pat),
        "TareDT": pick(text, r"Tare\.\s*\d+\s*Kgs\s*" + dt_pat),
    }


# ============= REAL-TIME PROCESSING =============

def process_weighment(info):
    completed = load_json(COMPLETED_FILE)
    pending = load_json(PENDING_FILE)

    rst = info["RST"]
    if not rst:
        return

    tare = bool(info["TareKg"])
    gross = bool(info["GrossKg"])
    tare_dt = parse_dt(info["TareDT"])
    gross_dt = parse_dt(info["GrossDT"])

    # ENTRY
    if (tare and not gross) or (gross and not tare):
        in_type = "Tare" if tare else "Gross"
        in_weight = info["TareKg"] if tare else info["GrossKg"]
        in_time = tare_dt if tare else gross_dt
        out_type = "Gross" if tare else "Tare"

        entry = {
            "RST": rst,
            "Vehicle": info["Vehicle"],
            "Party": info["Party"],
            "Material": info["Material"],
            "InTime": in_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Pending": out_type
        }

        # Remove if old exists
        pending = [p for p in pending if p["RST"] != rst]
        pending.append(entry)
        save_json(PENDING_FILE, pending)

        msg = (
            f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
            f"RST {rst} | {info['Vehicle']} | {info['Party']} | {info['Material']}\n"
            f"IN {format_12h(in_time)} | {in_type}: {in_weight} Kg\n"
            f"Pending {out_type}"
        )
        send_telegram(msg)
        return

    # COMPLETION
    if tare and gross and tare_dt and gross_dt:
        in_time = min(tare_dt, gross_dt)
        out_time = max(tare_dt, gross_dt)
        net = abs(int(info["GrossKg"]) - int(info["TareKg"]))

        record = {
            "RST": rst,
            "Vehicle": info["Vehicle"],
            "Party": info["Party"],
            "Material": info["Material"],
            "InTime": in_time.strftime("%Y-%m-%d %H:%M:%S"),
            "OutTime": out_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Net": net,
            "AlertSent": False
        }

        # Remove old pending entry
        pending = [p for p in pending if p["RST"] != rst]
        save_json(PENDING_FILE, pending)

        # Add to completed
        completed = [c for c in completed if c["RST"] != rst]
        completed.append(record)
        save_json(COMPLETED_FILE, completed)

        # Real-time alert
        msg = (
            f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
            f"RST {rst} | {info['Vehicle']} | {info['Party']} | {info['Material']}\n"
            f"IN {format_12h(in_time)} | OUT {format_12h(out_time)} | NET {net} Kg"
        )
        send_telegram(msg)
        record["AlertSent"] = True
        save_json(COMPLETED_FILE, completed)


# ============= MISSED ALERT RECOVERY =============

def recover_missed_alerts():
    completed = load_json(COMPLETED_FILE)
    for r in completed[-15:]:  # last 15 records
        if not r.get("AlertSent", False):
            in_t = datetime.strptime(r["InTime"], "%Y-%m-%d %H:%M:%S")
            out_t = datetime.strptime(r["OutTime"], "%Y-%m-%d %H:%M:%S")

            msg = (
                f"⚠️ MISSED ALERT RECOVERED ⚠️\n\n"
                f"RST {r['RST']} | {r['Vehicle']} | {r['Party']} | {r['Material']}\n"
                f"IN {format_12h(in_t)} | OUT {format_12h(out_t)} | NET {r['Net']} Kg"
            )
            send_telegram(msg)

            r["AlertSent"] = True
    save_json(COMPLETED_FILE, completed)


# ============= DAILY SUMMARY AT 10 AM =============

def send_daily_summary():
    now = now_ist()
    if now.hour != 10 or now.minute != 0:
        return

    completed = load_json(COMPLETED_FILE)
    pending = load_json(PENDING_FILE)

    start = (now - timedelta(days=1)).replace(hour=10, minute=0, second=0)
    end = now.replace(hour=10, minute=0, second=0)

    msg = f"📊 TODAY’S SUMMARY ({now.strftime('%d-%b %I:%M %p')})\n\n"

    # Completed
    for r in completed:
        out_dt = datetime.strptime(r["OutTime"], "%Y-%m-%d %H:%M:%S")
        if start <= out_dt <= end:
            in_dt = datetime.strptime(r["InTime"], "%Y-%m-%d %H:%M:%S")
            msg += (
                f"RST {r['RST']} | {r['Vehicle']} | {r['Party']} | {r['Material']} | "
                f"IN {format_12h(in_dt)} | OUT {format_12h(out_dt)} | NET {r['Net']} Kg\n"
            )

    # Pending
    for p in pending:
        in_dt = datetime.strptime(p["InTime"], "%Y-%m-%d %H:%M:%S")
        msg += (
            f"RST {p['RST']} | {p['Vehicle']} | {p['Party']} | {p['Material']} | "
            f"IN {format_12h(in_dt)} | Pending {p['Pending']}\n"
        )

    send_telegram(msg)


# ============= CHECK MAIL (last 20) =============

def check_mail():
    processed = set(load_json(PROCESSED_FILE))

    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    _, data = mail.uid("search", None, "ALL")
    uids = [int(x) for x in data[0].split()]
    recent = uids[-20:]

    for uid in recent:
        if uid in processed:
            continue

        _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = safe_decode(msg.get("Subject")).upper()
        if "WEIGH" not in subject and "SLIP" not in subject:
            continue

        for part in msg.walk():
            if "pdf" in part.get_content_type():
                pdf_bytes = part.get_payload(decode=True)
                if pdf_bytes:
                    info = extract_from_pdf(pdf_bytes)
                    process_weighment(info)
                    processed.add(uid)

    save_json(PROCESSED_FILE, list(processed))
    mail.logout()


# ============= MAIN LOOP =============

if __name__ == "__main__":
    while True:
        try:
            check_mail()
            recover_missed_alerts()
            send_daily_summary()
        except Exception as e:
            print("Error:", e)
        time.sleep(30)