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

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

ENTRY_MEM_FILE = "sent_entry.json"
COMP_MEM_FILE = "sent_complete.json"


# ---------------- TIME HELPERS ---------------- #

def fmt(dt):
    if not dt:
        return "Time N/A"
    return dt.strftime("%d-%b-%y | %I:%M %p")


def parse_datetime(date_str, time_str):
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%d-%b-%y %I:%M:%S %p")
    except:
        return None


# ---------------- TELEGRAM ---------------- #

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        print("[ERR] Telegram send error")


# ---------------- MEMORY HELPERS ---------------- #

def load_mem(path):
    if not os.path.exists(path):
        return set()
    try:
        return set(json.load(open(path)))
    except:
        return set()


def save_mem(path, data):
    json.dump(list(data), open(path, "w"), indent=2)


# ---------------- PDF EXTRACTION ---------------- #

def extract_from_pdf(pdf_bytes):
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except:
        print("[ERR] PDF read failure")
        return {}

    # Gross
    g = re.search(
        r"Gross\.\s*:\s*(\d+)\s*Kgs\s+(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s+[AP]M)",
        text)

    # Tare
    t = re.search(
        r"Tare\.\s*:\s*(\d+)\s*Kgs\s+(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s+[AP]M)",
        text)

    gross_wt = int(g.group(1)) if g else None
    gross_dt = parse_datetime(g.group(2), g.group(3)) if g else None

    tare_wt = int(t.group(1)) if t else None
    tare_dt = parse_datetime(t.group(2), t.group(3)) if t else None

    rst = pick(text, r"RST\s*:\s*(\d+)")
    vehicle = pick(text, r"Vehicle\s*No\s*:\s*([A-Z0-9\-]+)")
    party = pick(text, r"PARTY\s*NAME\s*:\s*([A-Za-z0-9 ]+)")
    material = pick(text, r"MATERIAL\s*:\s*([A-Za-z0-9 ]+)")

    return {
        "RST": rst,
        "Vehicle": vehicle,
        "Party": party,
        "Material": clean_material(material),
        "Gross": gross_wt,
        "GrossTime": gross_dt,
        "Tare": tare_wt,
        "TareTime": tare_dt
    }


def pick(text, pattern):
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# ---------------- SCAN EMAILS ---------------- #

def scan_last_50():
    yard = {}
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    _, data = mail.uid("search", None, "ALL")
    uids = [int(x) for x in data[0].split()]
    recent = uids[-50:]

    for uid in recent:
        _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subject = safe_decode(msg.get("Subject")).upper()

        if "WEIGH" not in subject and "SLIP" not in subject:
            continue

        for part in msg.walk():
            if "pdf" in part.get_content_type():
                info = extract_from_pdf(part.get_payload(decode=True))
                if info and info["RST"]:
                    yard[info["RST"]] = info

    print(f"[SCAN] {len(yard)} entries found")
    mail.logout()
    return yard


def safe_decode(value):
    if not value:
        return ""
    out = []
    for part, enc in decode_header(value):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


# ---------------- ALERT LOGIC ---------------- #

def send_alerts(yard, sent_entry, sent_complete):

    for rst, d in yard.items():
        g = d["Gross"]
        gt = d["GrossTime"]
        t = d["Tare"]
        tt = d["TareTime"]

        # ----- ENTRY ONLY -----
        if (g and not t) or (t and not g):
            if rst in sent_entry:
                continue

            # determine first
            first_type = "Gross" if g else "Tare"
            first_wt = g if g else t
            first_dt = gt if g else tt

            second_type = "Tare" if g else "Gross"

            msg = (
                f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                f"🧾 RST : {rst}   🚛 {d['Vehicle']}\n"
                f"🏢 PARTY : {d['Party']}\n"
                f"🌾 MATERIAL : {d['Material']}\n\n"
                f"⟪ FIRST WEIGHMENT ⟫\n"
                f"⚖ {first_type} : {first_wt} Kg\n"
                f"🕒 {fmt(first_dt)}\n\n"
                f"⟪ SECOND WEIGHMENT ⟫ Pending\n"
                f"⚖ {second_type} : Pending\n\n"
                f"🟡 STATUS : VEHICLE INSIDE YARD"
            )

            send_telegram(msg)
            sent_entry.add(rst)
            print(f"[ENTRY] Sent RST {rst}")
            continue

        # ----- COMPLETED -----
        if g and t:
            if rst in sent_complete:
                continue

            # figure order
            if gt < tt:
                first_type, first_wt, first_dt = "Gross", g, gt
                second_type, second_wt, second_dt = "Tare", t, tt
            else:
                first_type, first_wt, first_dt = "Tare", t, tt
                second_type, second_wt, second_dt = "Gross", g, gt

            net = abs(g - t)

            msg = (
                f"⚖️ WEIGHMENT ALERT ⚖️\n\n"
                f"🧾 RST : {rst}   🚛 {d['Vehicle']}\n"
                f"🏢 PARTY : {d['Party']}\n"
                f"🌾 MATERIAL : {d['Material']}\n\n"
                f"⟪ FIRST WEIGHMENT ⟫\n"
                f"⚖ {first_type} : {first_wt} Kg\n"
                f"🕒 {fmt(first_dt)}\n\n"
                f"⟪ SECOND WEIGHMENT ⟫\n"
                f"⚖ {second_type} : {second_wt} Kg\n"
                f"🕒 {fmt(second_dt)}\n\n"
                f"🔵 NET LOAD : {net} Kg\n\n"
                f"🟢 STATUS : WEIGHMENT COMPLETED"
            )

            send_telegram(msg)
            sent_complete.add(rst)
            print(f"[COMPLETE] Sent RST {rst}")

    save_mem(ENTRY_MEM_FILE, sent_entry)
    save_mem(COMP_MEM_FILE, sent_complete)


# ---------------- MAIN LOOP ---------------- #

if __name__ == "__main__":
    while True:
        try:
            yard = scan_last_50()

            sent_entry = load_mem(ENTRY_MEM_FILE)
            sent_complete = load_mem(COMP_MEM_FILE)

            send_alerts(yard, sent_entry, sent_complete)

        except Exception as e:
            print("[ERR]", e)

        time.sleep(30)