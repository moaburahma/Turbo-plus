from flask import Flask, request
import os
import requests
from dotenv import load_dotenv
import core

load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GRAPH_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"


def send_text(to, body):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    requests.post(GRAPH_URL, headers=headers, json=payload)


def send_buttons(to, body_text, buttons):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp", "to": to, "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body_text},
                        "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]}}
    }
    requests.post(GRAPH_URL, headers=headers, json=payload)


def send_main_menu(phone):
    send_buttons(phone, core.get_msg("welcome_menu"),
                 [{"id": "start_order", "title": core.get_msg("button_order")},
                  {"id": "start_complaint", "title": core.get_msg("button_complaint")}])


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    try:
        change = data["entry"][0]["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return "OK", 200

        message = messages[0]
        phone = message["from"]
        customer = core.get_or_create_customer(phone, "whatsapp")
        individual_enabled = core.get_setting("individual_enabled") == "1"

        if message["type"] == "interactive":
            button_id = message["interactive"]["button_reply"]["id"]

            if button_id == "start_order":
                if individual_enabled:
                    core.set_customer_state(customer["id"], "awaiting_service_type")
                    send_buttons(phone, core.get_msg("choose_service_type"),
                                 [{"id": "type_individual", "title": core.get_msg("button_individual")},
                                  {"id": "type_package", "title": core.get_msg("button_package")}])
                else:
                    core.set_customer_state(customer["id"], "awaiting_description")
                    send_text(phone, core.get_msg("ask_description"))

            elif button_id == "start_complaint":
                core.set_customer_state(customer["id"], "awaiting_complaint_order")
                send_text(phone, core.get_msg("complaint_ask_order"))

            elif button_id == "type_individual":
                core.set_customer_state(customer["id"], "awaiting_vehicle")
                send_buttons(phone, core.get_msg("ask_vehicle"),
                             [{"id": "vehicle_car", "title": core.get_msg("button_car")},
                              {"id": "vehicle_moto", "title": core.get_msg("button_moto")}])

            elif button_id == "type_package":
                core.set_customer_state(customer["id"], "awaiting_description")
                send_text(phone, core.get_msg("ask_description"))

            elif button_id in ("vehicle_car", "vehicle_moto"):
                vehicle = core.get_msg("button_car") if button_id == "vehicle_car" else core.get_msg("button_moto")
                core.set_customer_field(customer["id"], "draft_vehicle", vehicle)
                core.set_customer_state(customer["id"], "awaiting_pickup")
                send_text(phone, core.get_msg("ask_pickup"))

        elif message["type"] == "text":
            text_body = message["text"]["body"].strip()
            state = customer["state"]

            if state == "awaiting_pickup":
                core.set_customer_field(customer["id"], "draft_pickup", text_body)
                core.set_customer_state(customer["id"], "awaiting_dropoff")
                send_text(phone, core.get_msg("ask_dropoff"))

            elif state == "awaiting_dropoff":
                description = f"من {customer['draft_pickup']} إلى {text_body}"
                core.set_customer_field(customer["id"], "draft_details", description)
                core.set_customer_state(customer["id"], "awaiting_price")
                send_text(phone, core.get_msg("ask_price", min_price=core.MIN_PRICE))

            elif state == "awaiting_description":
                core.set_customer_field(customer["id"], "draft_details", text_body)
                core.set_customer_state(customer["id"], "awaiting_price")
                send_text(phone, core.get_msg("ask_price", min_price=core.MIN_PRICE))

            elif state == "awaiting_price":
                try:
                    price = float(text_body)
                except ValueError:
                    send_text(phone, core.get_msg("price_invalid"))
                    return "OK", 200
                if price < core.MIN_PRICE:
                    send_text(phone, core.get_msg("price_too_low", min_price=core.MIN_PRICE))
                    return "OK", 200

                order_type = "فردي" if customer["draft_vehicle"] else "طلبات"
                order_code = core.create_order(customer["id"], order_type, customer["draft_vehicle"],
                                                customer["draft_details"], price, "whatsapp")
                core.set_customer_state(customer["id"], "idle")
                core.set_customer_field(customer["id"], "draft_vehicle", None)
                send_text(phone, core.get_msg("order_confirmed", order_code=order_code, price=price))

            elif state == "awaiting_complaint_order":
                core.set_customer_field(customer["id"], "draft_details", text_body)
                core.set_customer_state(customer["id"], "awaiting_complaint_message")
                send_text(phone, core.get_msg("complaint_ask_message"))

            elif state == "awaiting_complaint_message":
                try:
                    order_code = int(customer["draft_details"])
                except (TypeError, ValueError):
                    order_code = None
                core.create_complaint(customer["id"], order_code, text_body)
                core.set_customer_state(customer["id"], "idle")
                send_text(phone, core.get_msg("complaint_confirmed"))

            else:
                send_main_menu(phone)

    except (KeyError, IndexError, TypeError) as e:
        print("مفيش رسالة فعلية جوه الـ payload:", e)

    return "OK", 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)