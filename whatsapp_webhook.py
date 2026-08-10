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

INDIVIDUAL_FORM_TEXT = (
    "تمام، اكتب البيانات دي كلها في رسالة واحدة، كل بيانة في سطر لوحدها وبنفس الترتيب:\n"
    "١) مكان التحرك (من)\n"
    "٢) مكان التوصيل (إلى)\n"
    "٣) السعر المعروض (بالجنيه)\n"
    "٤) رقم التليفون أو الواتساب للتواصل"
)
PACKAGE_FORM_TEXT = (
    "تمام، اكتب البيانات دي كلها في رسالة واحدة، كل بيانة في سطر لوحدها وبنفس الترتيب:\n"
    "١) تفاصيل الطلب المطلوب\n"
    "٢) السعر المعروض (بالجنيه)\n"
    "٣) رقم التليفون أو الواتساب للتواصل"
)


def get_order_options():
    individual_enabled = core.get_setting("individual_enabled") == "1"
    packages_enabled = core.get_setting("packages_enabled") != "0"
    return individual_enabled, packages_enabled


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
    """بيبعت رسالة نصية ومعاها زرار إلغاء واحد بس، عشان العميل يقدر يلغي وهو بيدخل بياناته."""
    send_buttons(to, body_text, [{"id": "cancel_flow", "title": "إلغاء ❌"}])


def send_main_menu(phone):
    send_buttons(phone, core.get_msg("welcome_menu"),
                 [{"id": "start_order", "title": core.get_msg("button_order")},
                  {"id": "start_complaint", "title": core.get_msg("button_complaint")}])


def parse_combined_lines(text, expected_count):
    """بتفكّك رسالة العميل المجمّعة لأسطر، وبترجع أول expected_count سطر غير فاضي، أو None لو مش كفاية."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) < expected_count:
        return None
    return lines[:expected_count]


@whatsapp_bp.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403


@whatsapp_bp.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    # نرجّع "OK" لميتا فورًا من غير ما نستنى معالجة الرسالة، عشان ميتا متعتبرش الطلب "فشل" وتعيد إرسال نفس الرسالة تاني بعد تأخير
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
        individual_enabled, packages_enabled = get_order_options()

        # 1) أمر الإلغاء بيشتغل دايمًا، حتى لو البوت "ساكت" بسبب طلب شغال
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

        # 2) سكوت تام لو عنده طلب شغال (جديد أو قيد التوصيل) لحد ما يتقبل أو يخلص
        active_order = core.get_customer_active_order(customer["id"])
        if active_order:
            return

        if message["type"] == "interactive":
            button_id = message["interactive"]["button_reply"]["id"]

            if button_id == "start_order":
                if individual_enabled and packages_enabled:
                    core.set_customer_state(customer["id"], "awaiting_service_type")
                    send_buttons(phone, core.get_msg("choose_service_type"),
                                 [{"id": "type_individual", "title": core.get_msg("button_individual")},
                                  {"id": "type_package", "title": core.get_msg("button_package")}])
                elif individual_enabled:
                    core.set_customer_state(customer["id"], "awaiting_combined_individual")
                    send_with_cancel(phone, INDIVIDUAL_FORM_TEXT)
                elif packages_enabled:
                    core.set_customer_state(customer["id"], "awaiting_combined_package")
                    send_with_cancel(phone, PACKAGE_FORM_TEXT)
                else:
                    send_text(phone, "الخدمة مش متاحة دلوقتي، حاول تاني بعدين.")

            elif button_id == "cancel_flow":
                cancelled_code = core.cancel_customer_order(customer["id"])
                if cancelled_code:
                    send_text(phone, f"تم إلغاء طلبك رقم #{cancelled_code} ✅")
                else:
                    send_text(phone, "تم إلغاء العملية الحالية.")

            elif button_id == "start_complaint":
                core.set_customer_state(customer["id"], "awaiting_complaint_order")
                send_text(phone, core.get_msg("complaint_ask_order"))

            elif button_id == "type_individual":
                core.set_customer_state(customer["id"], "awaiting_combined_individual")
                send_with_cancel(phone, INDIVIDUAL_FORM_TEXT)

            elif button_id == "type_package":
                core.set_customer_state(customer["id"], "awaiting_combined_package")
                send_with_cancel(phone, PACKAGE_FORM_TEXT)

        elif message["type"] == "text":
            text_body = message["text"]["body"].strip()
            state = customer["state"]

            if state == "awaiting_combined_individual":
                fields = parse_combined_lines(text_body, 4)
                if not fields:
                    send_with_cancel(phone, "البيانات ناقصة. " + INDIVIDUAL_FORM_TEXT)
                    return
                pickup, dropoff, price_text, contact_info = fields
                try:
                    price = float(price_text)
                except ValueError:
                    send_with_cancel(phone, "السعر لازم يكون رقم صحيح. " + INDIVIDUAL_FORM_TEXT)
                    return
                min_price = core.get_min_price("فردي")
                if price < min_price:
                    send_with_cancel(phone, core.get_msg("price_too_low", min_price=min_price) + "\n\n" + INDIVIDUAL_FORM_TEXT)
                    return
                description = f"من {pickup} إلى {dropoff}"
                order_code = core.create_order(customer["id"], "فردي", None, description, price, "whatsapp", contact_info)
                core.set_customer_state(customer["id"], "idle")
                send_buttons(
                    phone, f"تم استلام طلبك رقم #{order_code} ✅ وجاري عرضه على المناديب دلوقتي، هنبلغك أول ما حد يوافق.",
                    [{"id": "cancel_flow", "title": "إلغاء الطلب ❌"}, {"id": "start_complaint", "title": "قدم شكوى"}]
                )

            elif state == "awaiting_combined_package":
                fields = parse_combined_lines(text_body, 3)
                if not fields:
                    send_with_cancel(phone, "البيانات ناقصة. " + PACKAGE_FORM_TEXT)
                    return
                details, price_text, contact_info = fields
                try:
                    price = float(price_text)
                except ValueError:
                    send_with_cancel(phone, "السعر لازم يكون رقم صحيح. " + PACKAGE_FORM_TEXT)
                    return
                min_price = core.get_min_price("طلبات")
                if price < min_price:
                    send_with_cancel(phone, core.get_msg("price_too_low", min_price=min_price) + "\n\n" + PACKAGE_FORM_TEXT)
                    return
                order_code = core.create_order(customer["id"], "طلبات", None, details, price, "whatsapp", contact_info)
                core.set_customer_state(customer["id"], "idle")
                send_buttons(
                    phone, f"تم استلام طلبك رقم #{order_code} ✅ وجاري عرضه على المناديب دلوقتي، هنبلغك أول ما حد يوافق.",
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

            elif state == "awaiting_rating":
                order_code = int(customer["draft_details"]) if customer.get("draft_details") else None
                try:
                    rating = int(text_body)
                    if 1 <= rating <= 5 and order_code:
                        core.submit_rating(customer["id"], order_code, rating)
                        core.set_customer_field(customer["id"], "draft_details", None)
                        core.set_customer_state(customer["id"], "idle")
                        send_buttons(phone, "شكرًا لتقييمك! 🙏\n\n" + core.get_msg("welcome_menu"),
                                     [{"id": "start_order", "title": core.get_msg("button_order")},
                                      {"id": "start_complaint", "title": core.get_msg("button_complaint")}])
                        return
                except ValueError:
                    pass
                # أي حاجة تانية غير رقم من 1 لـ 5: نعتبره مش عايز يقيّم، ونكمل عادي من غير ما نلحّ عليه
                core.set_customer_field(customer["id"], "draft_details", None)
                core.set_customer_state(customer["id"], "idle")
                send_main_menu(phone)

            else:
                send_main_menu(phone)

    except (KeyError, IndexError, TypeError) as e:
        print("مفيش رسالة فعلية جوه الـ payload:", e)
    except Exception as e:
        print("خطأ غير متوقع أثناء معالجة رسالة واتساب:", e)