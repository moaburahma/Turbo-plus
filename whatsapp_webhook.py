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
    """بيبعت رسالة نصية ومعاها زرار إلغاء واحد بس."""
    send_buttons(to, body_text, [{"id": "cancel_flow", "title": "إلغاء ❌"}])


def send_main_menu(phone):
    send_buttons(phone, core.get_msg("welcome_menu"),
                 [{"id": "start_order", "title": core.get_msg("button_order")},
                  {"id": "start_complaint", "title": core.get_msg("button_complaint")}])


def build_combined_form():
    """بتبني نص الفورم المجمّع ديناميكيًا حسب إعدادات الأدمن الحالية (تفعيل أفراد/طلبات + الحد الأدنى للسعر).
    بترجع (نص الرسالة، قايمة أسماء الحقول بنفس ترتيب الأسطر المطلوبة من العميل)."""
    individual_enabled, packages_enabled = get_order_options()
    min_individual = core.get_min_price("فردي")
    min_packages = core.get_min_price("طلبات")

    lines = ["تمام، اكتب البيانات دي كلها في رسالة واحدة، كل بيانة في سطر لوحدها وبنفس الترتيب:"]
    fields = []
    n = 1

    if individual_enabled and packages_enabled:
        lines.append(f"{n}) نوع الخدمة (اكتب: أفراد أو طلبات)")
        fields.append("service_type")
        n += 1

    if individual_enabled:
        lines.append(f"{n}) نوع المركبة لو الخدمة أفراد (سيارة أو موتوسيكل) - اكتب خط - لو طلبات")
        fields.append("vehicle")
        n += 1

    lines.append(f"{n}) تفاصيل الطلب (مكان التحرك ومكان التوصيل لو أفراد، أو وصف الطلب لو طلبات)")
    fields.append("details")
    n += 1

    price_notes = []
    if individual_enabled:
        price_notes.append(f"{min_individual:g} جنيه للأفراد")
    if packages_enabled:
        price_notes.append(f"{min_packages:g} جنيه للطلبات")
    lines.append(f"{n}) السعر المعروض بالجنيه (الحد الأدنى: {' / '.join(price_notes)})")
    fields.append("price")
    n += 1

    lines.append(f"{n}) رقم التليفون أو الواتساب للتواصل")
    fields.append("contact")

    return "\n".join(lines), fields


def parse_combined_lines(text, expected_count):
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

        # سكوت تام لو عنده طلب شغال (جديد أو قيد التوصيل) لحد ما يتقبل أو يخلص
        active_order = core.get_customer_active_order(customer["id"])
        if active_order:
            return

        if message["type"] == "interactive":
            button_id = message["interactive"]["button_reply"]["id"]

            if button_id == "start_order":
                individual_enabled, packages_enabled = get_order_options()
                if not individual_enabled and not packages_enabled:
                    send_text(phone, "الخدمة مش متاحة دلوقتي، حاول تاني بعدين.")
                else:
                    form_text, _ = build_combined_form()
                    core.set_customer_state(customer["id"], "awaiting_combined_order")
                    send_with_cancel(phone, form_text)

            elif button_id == "cancel_flow":
                cancelled_code = core.cancel_customer_order(customer["id"])
                if cancelled_code:
                    send_text(phone, f"تم إلغاء طلبك رقم #{cancelled_code} ✅")
                else:
                    send_text(phone, "تم إلغاء العملية الحالية.")

            elif button_id == "start_complaint":
                core.set_customer_state(customer["id"], "awaiting_complaint_order")
                send_text(phone, core.get_msg("complaint_ask_order"))

        elif message["type"] == "text":
            text_body = message["text"]["body"].strip()
            state = customer["state"]

            if state == "awaiting_combined_order":
                individual_enabled, packages_enabled = get_order_options()
                form_text, fields = build_combined_form()
                parsed = parse_combined_lines(text_body, len(fields))
                if not parsed:
                    send_with_cancel(phone, "البيانات ناقصة، تأكد إنك كتبت كل بيانة في سطر منفصل.\n\n" + form_text)
                    return
                row = dict(zip(fields, parsed))

                if "service_type" in row:
                    st = row["service_type"]
                    if "فرد" in st:
                        order_type = "فردي"
                    elif "طلب" in st:
                        order_type = "طلبات"
                    else:
                        send_with_cancel(phone, "من فضلك اكتب 'أفراد' أو 'طلبات' بالظبط في نوع الخدمة.\n\n" + form_text)
                        return
                else:
                    order_type = "فردي" if individual_enabled else "طلبات"

                if order_type == "فردي" and not individual_enabled:
                    send_with_cancel(phone, "خدمة توصيل الأفراد مش متاحة دلوقتي.\n\n" + form_text)
                    return
                if order_type == "طلبات" and not packages_enabled:
                    send_with_cancel(phone, "خدمة الطلبات مش متاحة دلوقتي.\n\n" + form_text)
                    return

                vehicle_type = None
                if order_type == "فردي" and "vehicle" in row:
                    vt = row["vehicle"]
                    if "موتو" in vt or "دراج" in vt:
                        vehicle_type = "موتوسيكل"
                    elif "سيار" in vt or "عرب" in vt:
                        vehicle_type = "سيارة"
                    else:
                        vehicle_type = vt

                try:
                    price = float(row["price"])
                except ValueError:
                    send_with_cancel(phone, "السعر لازم يكون رقم صحيح.\n\n" + form_text)
                    return
                min_price = core.get_min_price(order_type)
                if price < min_price:
                    send_with_cancel(phone, core.get_msg("price_too_low", min_price=min_price) + "\n\n" + form_text)
                    return

                order_code = core.create_order(customer["id"], order_type, vehicle_type, row["details"], price, "whatsapp", row["contact"])
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
                core.set_customer_field(customer["id"], "draft_details", None)
                core.set_customer_state(customer["id"], "idle")
                send_main_menu(phone)

            else:
                send_main_menu(phone)

    except (KeyError, IndexError, TypeError) as e:
        print("مفيش رسالة فعلية جوه الـ payload:", e)
    except Exception as e:
        print("خطأ غير متوقع أثناء معالجة رسالة واتساب:", e)