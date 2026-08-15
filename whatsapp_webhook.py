from flask import Blueprint, request
import os
import requests
import threading
from dotenv import load_dotenv
import core

load_dotenv()

whatsapp_bp = Blueprint("whatsapp_webhook", __name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GRAPH_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

CANCEL_WORDS = ("الغاء", "إلغاء", "الغاء الطلب", "إلغاء الطلب", "cancel", "Cancel")


def get_order_options():
    individual_enabled = core.get_setting("individual_enabled") == "1"
    packages_enabled = core.get_setting("packages_enabled") != "0"
    return individual_enabled, packages_enabled


def msg_enabled(key):
    """بتتأكد من إعداد الأدمن هل الرسالة دي مفعّلة (ظاهرة) ولا لأ. الافتراضي مفعّلة لو الإعداد مش موجود."""
    return core.get_setting(key) != "0"


def send_text(to, body):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    requests.post(GRAPH_URL, headers=headers, json=payload, timeout=10)


def send_buttons(to, body_text, buttons):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp", "to": to, "type": "interactive",
        "interactive": {"type": "button", "body": {"text": body_text},
                        "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]}}
    }
    requests.post(GRAPH_URL, headers=headers, json=payload, timeout=10)


def send_with_cancel(to, body_text):
    send_buttons(to, body_text, [{"id": "cancel_flow", "title": "إلغاء ❌"}])


def send_main_menu(phone):
    # رسالة 1: ممكن تتقفل من الإعدادات
    if not msg_enabled("whatsapp_show_msg1_welcome"):
        return
    send_buttons(phone, core.get_msg("welcome_menu"),
                 [{"id": "start_order", "title": core.get_msg("button_order")},
                  {"id": "start_complaint", "title": core.get_msg("button_complaint")}])


@whatsapp_bp.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403


@whatsapp_bp.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    threading.Thread(target=process_whatsapp_message, args=(data,), daemon=True).start()
    return "OK", 200


def process_whatsapp_message(data):
    try:
        change = data["entry"][0]["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return

        message = messages[0]
        phone = message["from"]
        customer = core.get_or_create_customer(phone, "whatsapp")

        # 0) العميل المحظور متتجاهل رسائله تمامًا (من غير ما نبعتله أي رد، توفير للفلوس)
        if customer.get("is_blocked"):
            return

        # 1) أمر الإلغاء النصي بيشتغل دايمًا
        if message["type"] == "text":
            text_body = message["text"]["body"].strip()
            if text_body in CANCEL_WORDS:
                active = core.get_customer_active_order(customer["id"])
                if active and active["status"] == "قيد التوصيل":
                    send_text(phone, "طلبك قيد التنفيذ حاليًا ومش ممكن يتلغي دلوقتي، تواصل مع المندوب مباشرة لو محتاج.")
                else:
                    cancelled_code = core.cancel_customer_order(customer["id"])
                    if cancelled_code:
                        send_text(phone, f"تم إلغاء طلبك رقم #{cancelled_code} ✅")
                    else:
                        send_text(phone, "تم إلغاء العملية الحالية.")
                return

        # 2) زرار "إلغاء" و"قدم شكوى" لازم يشتغلوا حتى لو الطلب لسه شغال (قبل فحص السكوت، عشان ميتبلعوش)
        if message["type"] == "interactive":
            button_id = message["interactive"]["button_reply"]["id"]
            if button_id == "cancel_flow":
                active = core.get_customer_active_order(customer["id"])
                if active and active["status"] == "قيد التوصيل":
                    send_text(phone, "طلبك قيد التنفيذ حاليًا ومش ممكن يتلغي دلوقتي، تواصل مع المندوب مباشرة لو محتاج.")
                else:
                    cancelled_code = core.cancel_customer_order(customer["id"])
                    if cancelled_code:
                        send_text(phone, f"تم إلغاء طلبك رقم #{cancelled_code} ✅")
                    else:
                        send_text(phone, "تم إلغاء العملية الحالية.")
                return
            if button_id == "start_complaint":
                core.set_customer_state(customer["id"], "awaiting_complaint_order")
                send_text(phone, core.get_msg("complaint_ask_order"))
                return

        # 3) سكوت تام لو عنده طلب شغال (جديد أو قيد التوصيل)، إلا لو بيكمل شكوى فعلاً بدأها
        active_order = core.get_customer_active_order(customer["id"])
        complaint_states = ("awaiting_complaint_order", "awaiting_complaint_message")
        if active_order and customer["state"] not in complaint_states:
            return

        if message["type"] == "interactive":
            button_id = message["interactive"]["button_reply"]["id"]

            if button_id == "start_order":
                individual_enabled, packages_enabled = get_order_options()
                msg2_body = core.get_msg("whatsapp_msg2_details")
                if not individual_enabled and not packages_enabled:
                    send_text(phone, "الخدمة مش متاحة دلوقتي، حاول تاني بعدين.")
                elif individual_enabled and packages_enabled:
                    core.set_customer_state(customer["id"], "awaiting_type_choice")
                    if msg_enabled("whatsapp_show_msg2_details"):
                        send_buttons(
                            phone, msg2_body,
                            [{"id": "vehicle_car", "title": "سيارة"}, {"id": "vehicle_moto", "title": "موتوسيكل"},
                             {"id": "type_package", "title": "طلبات"}]
                        )
                elif individual_enabled:
                    core.set_customer_state(customer["id"], "awaiting_type_choice")
                    if msg_enabled("whatsapp_show_msg2_details"):
                        send_buttons(
                            phone, msg2_body,
                            [{"id": "vehicle_car", "title": "سيارة"}, {"id": "vehicle_moto", "title": "موتوسيكل"},
                             {"id": "cancel_flow", "title": "إلغاء ❌"}]
                        )
                else:  # packages فقط
                    core.set_customer_field(customer["id"], "draft_vehicle", "PACKAGE")
                    core.set_customer_state(customer["id"], "awaiting_details")
                    if msg_enabled("whatsapp_show_msg2_details"):
                        send_with_cancel(phone, msg2_body)

            elif button_id in ("vehicle_car", "vehicle_moto"):
                vehicle = "سيارة" if button_id == "vehicle_car" else "موتوسيكل"
                core.set_customer_field(customer["id"], "draft_vehicle", vehicle)
                core.set_customer_state(customer["id"], "awaiting_details")
                if msg_enabled("whatsapp_show_msg2_details"):
                    send_with_cancel(phone, f"تمام، اخترت {vehicle}. {core.get_msg('whatsapp_msg2_details')}")

            elif button_id == "type_package":
                core.set_customer_field(customer["id"], "draft_vehicle", "PACKAGE")
                core.set_customer_state(customer["id"], "awaiting_details")
                if msg_enabled("whatsapp_show_msg2_details"):
                    send_with_cancel(phone, core.get_msg("whatsapp_msg2_details"))

        elif message["type"] == "text":
            text_body = message["text"]["body"].strip()
            state = customer["state"]

            if state == "awaiting_details":
                core.set_customer_field(customer["id"], "draft_details", text_body)
                core.set_customer_state(customer["id"], "awaiting_price")
                order_type = "طلبات" if customer["draft_vehicle"] == "PACKAGE" else "فردي"
                min_price = core.get_min_price(order_type)
                if msg_enabled("whatsapp_show_msg3_price"):
                    send_with_cancel(phone, core.get_msg("ask_price", min_price=min_price))

            elif state == "awaiting_price":
                try:
                    price = float(text_body)
                except ValueError:
                    send_with_cancel(phone, core.get_msg("price_invalid"))
                    return
                order_type = "طلبات" if customer["draft_vehicle"] == "PACKAGE" else "فردي"
                min_price = core.get_min_price(order_type)
                if price < min_price:
                    send_with_cancel(phone, core.get_msg("price_too_low", min_price=min_price))
                    return
                vehicle_type = None if customer["draft_vehicle"] == "PACKAGE" else customer["draft_vehicle"]
                # رقم واتساب العميل نفسه هو رقم التواصل، مفيش داعي نسأل عليه في رسالة منفصلة
                order_code = core.create_order(customer["id"], order_type, vehicle_type, customer["draft_details"], price, "whatsapp", phone)
                core.set_customer_state(customer["id"], "idle")
                core.set_customer_field(customer["id"], "draft_vehicle", None)
                if msg_enabled("whatsapp_show_msg4_received"):
                    send_buttons(
                        phone, core.get_msg("whatsapp_msg4_received", order_code=order_code),
                        [{"id": "cancel_flow", "title": "إلغاء الطلب ❌"}, {"id": "start_complaint", "title": "قدم شكوى"}]
                    )

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
    except Exception as e:
        print("خطأ غير متوقع أثناء معالجة رسالة واتساب:", e)