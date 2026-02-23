import requests

# ==============================
# 🔹 YOUR FIXED CONFIG
# ==============================

WHATSAPP_TOKEN = "EAAd3lLDpMAUBQ3qpb2fTnyxw7Rqh3esPikmuzGRZBzsllzRZBxZCfooRaRoXoh7jpBZBYJ5G4Yemil47AgVQIY5v4PX3wJZA1Gs445btkr82Va0j7NKCXNFKd8SUhVRmKZBLO5VsIkXVhaE7cz7ESaEJ9rwYkKYrsNoSXVjEqbHHBn3HrXYZAOzL9SPKtUdWAZDZD"
PHONE_NUMBER_ID = "1026390710554052"

NUMBERS = [
    "918181923999",
    "919849399996"
]

# ==============================
# 🔹 SEND FUNCTION
# ==============================

def send_whatsapp(to_number, message_text):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    print("To:", to_number)
    print("Status:", response.status_code)
    print("Response:", response.text)
    print("-" * 50)


# ==============================
# 🔹 TEST MESSAGE
# ==============================

if __name__ == "__main__":
    for number in NUMBERS:
        send_whatsapp(number, "🔥 WhatsApp automation is working!")
