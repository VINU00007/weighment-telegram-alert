import os
import time
import requests

# ==============================
# WHATSAPP TEST CONFIG
# ==============================

WHATSAPP_TOKEN = "EAAd3lLDpMAUBQ3qpb2fTnyxw7Rqh3esPikmuzGRZBzsllzRZBxZCfooRaRoXoh7jpBZBYJ5G4Yemil47AgVQIY5v4PX3wJZA1Gs445btkr82Va0j7NKCXNFKd8SUhVRmKZBLO5VsIkXVhaE7cz7ESaEJ9rwYkKYrsNoSXVjEqbHHBn3HrXYZAOzL9SPKtUdWAZDZD"
PHONE_NUMBER_ID = "1026390710554052"

RECIPIENTS = [
    "918181923999",
    "919849399996"
]

WATCH_FOLDER = "/app/weighment_slips"

if not os.path.exists(WATCH_FOLDER):
    os.makedirs(WATCH_FOLDER)


# ==============================
# SEND TEMPLATE MESSAGE
# ==============================

def send_template_message():
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    for number in RECIPIENTS:
        payload = {
            "messaging_product": "whatsapp",
            "to": number,
            "type": "template",
            "template": {
                "name": "hello_world",
                "language": {
                    "code": "en_US"
                }
            }
        }

        response = requests.post(url, headers=headers, json=payload)

        print("To:", number)
        print("Status:", response.status_code)
        print("Response:", response.text)
        print("-" * 50)


# ==============================
# MONITOR FOLDER
# ==============================

def monitor_folder():
    print("🚀 Test WhatsApp Automation Started...")
    print("Watching folder:", WATCH_FOLDER)

    already_seen = set(os.listdir(WATCH_FOLDER))

    while True:
        time.sleep(5)

        current_files = set(os.listdir(WATCH_FOLDER))
        new_files = current_files - already_seen

        for file in new_files:
            print("New file detected:", file)
            send_template_message()

        already_seen = current_files


# ==============================
# START
# ==============================

if __name__ == "__main__":
    send_template_message()  # startup test
    monitor_folder()
