import os
import threading
import time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import core

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")


def get_order_options():
    """بيرجع (individual_enabled, packages_enabled) حسب إعدادات الأدمن."""
    individual_enabled = core.get_setting("individual_enabled") == "1"
    packages_enabled = core.get_setting("packages_enabled") != "0"  # مفعّلة افتراضيًا لو الإعداد مش موجود
    return individual_enabled, packages_enabled


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    core.get_or_create_customer(chat_id, "telegram")
    kb = [[InlineKeyboardButton(core.get_msg("button_order"), callback_data="start_order")],
          [InlineKeyboardButton(core.get_msg("button_complaint"), callback_data="start_complaint")]]
    await update.message.reply_text(core.get_msg("welcome_menu"), reply_markup=InlineKeyboardMarkup(kb))


async def notify_drivers_group(context, order_code, order_type, details, price):
    """بيبعت إشعار الطلب الجديد لجروبات المناديب. من غير أي معلومات تواصل خاصة بالعميل."""
    groups = core.get_telegram_driver_groups()
    kb = [[InlineKeyboardButton(core.get_msg("button_accept"), callback_data=f"accept_{order_code}")]]
    text = core.get_msg("driver_new_order", order_code=order_code, details=details, price=price)
    text = f"{text}\n\nنوع الطلب: {order_type}"
    for g in groups:
        try:
            sent = await context.bot.send_message(chat_id=g["chat_id"], text=text, reply_markup=InlineKeyboardMarkup(kb))
            # بنسجل رقم الرسالة وجروبها عشان نقدر نعدلها لاحقًا لو حد قبل الطلب من مكان تاني (زي لوحة الويب)
        except Exception as e:
            print("فشل الإرسال لجروب", g["chat_id"], ":", e)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("accept_"):
        order_code = int(data.replace("accept_", ""))
        driver = core.get_driver_by_telegram_id(query.from_user.id)
        if driver is None:
            await query.answer("انت مش مسجل كمندوب، كلم الأدمن يضيفك.", show_alert=True)
            return
        ok, msg, order, customer, driver = core.accept_order(driver["id"], order_code)
        if not ok:
            # لو مقدرش ياخد الطلب (اتاخد قبله أو رصيده مش كافي)، منعدلش رسالة الجروب
            await query.answer(msg, show_alert=True)
            return

        # 1) نعدّل رسالة الجروب عشان كل المناديب يشوفوا إن الطلب اتاخد (من غير أي بيانات تواصل خاصة بالعميل)
        try:
            await query.edit_message_text(
                f"طلب #{order_code} — تم القبول ✅\nالمندوب: {driver['name']}\nحالة الطلب: قيد التوصيل"
            )
        except Exception as e:
            print(f"فشل تعديل رسالة الجروب للطلب #{order_code}:", e)

        # 2) نبعت معلومات التواصل الخاصة بالعميل في رسالة خاصة (DM) للمندوب اللي قبل بس
        contact_line = f"\nمعلومات التواصل: {order['contact_info']}" if order.get("contact_info") else ""
        private_text = (
            f"استلمت طلب #{order_code} بنجاح ✅\n"
            f"التفاصيل: {order['details']}\n"
            f"السعر: {order['price']} جنيه"
            f"{contact_line}"
        )
        core.send_telegram_private_message(query.from_user.id, private_text)
        return

    if data.startswith("finish_"):
        order_code = int(data.replace("finish_", ""))
        driver = core.get_driver_by_telegram_id(query.from_user.id)
        if driver is None:
            await query.answer("انت مش مسجل كمندوب.", show_alert=True)
            return
        ok, msg, order, customer, points_earned, new_points = core.finish_order(driver["id"], order_code)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        await query.edit_message_text(f"طلب #{order_code} — تم إنهاؤه ✅ بواسطة {driver['name']}")
        # ملحوظة: إشعار العميل وطلب التقييم بيتبعتوا تلقائيًا من جوه core.finish_order نفسها
        return

    chat_id = str(query.message.chat_id)
    customer = core.get_or_create_customer(chat_id, "telegram")
    individual_enabled, packages_enabled = get_order_options()

    if data == "start_order":
        if individual_enabled and packages_enabled:
            core.set_customer_state(customer["id"], "awaiting_service_type")
            kb = [[InlineKeyboardButton(core.get_msg("button_individual"), callback_data="type_individual")],
                  [InlineKeyboardButton(core.get_msg("button_package"), callback_data="type_package")],
                  [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_flow")]]
            await query.edit_message_text(core.get_msg("choose_service_type"), reply_markup=InlineKeyboardMarkup(kb))
        elif individual_enabled:
            core.set_customer_state(customer["id"], "awaiting_vehicle")
            kb = [[InlineKeyboardButton(core.get_msg("button_car"), callback_data="vehicle_car")],
                  [InlineKeyboardButton(core.get_msg("button_moto"), callback_data="vehicle_moto")],
                  [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_flow")]]
            await query.edit_message_text(core.get_msg("ask_vehicle"), reply_markup=InlineKeyboardMarkup(kb))
        elif packages_enabled:
            core.set_customer_state(customer["id"], "awaiting_description")
            await query.edit_message_text(core.get_msg("ask_description"), reply_markup=CANCEL_KB)
        else:
            await query.edit_message_text("الخدمة مش متاحة دلوقتي، حاول تاني بعدين.")

    elif data == "cancel_flow":
        cancelled_code = core.cancel_customer_order(customer["id"])
        if cancelled_code:
            await query.edit_message_text(f"تم إلغاء طلبك رقم #{cancelled_code} ✅")
        else:
            await query.edit_message_text("تم إلغاء العملية الحالية.")

    elif data == "start_complaint":
        core.set_customer_state(customer["id"], "awaiting_complaint_order")
        await query.edit_message_text(core.get_msg("complaint_ask_order"))

    elif data == "type_individual":
        core.set_customer_state(customer["id"], "awaiting_vehicle")
        kb = [[InlineKeyboardButton(core.get_msg("button_car"), callback_data="vehicle_car")],
              [InlineKeyboardButton(core.get_msg("button_moto"), callback_data="vehicle_moto")],
              [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_flow")]]
        await query.edit_message_text(core.get_msg("ask_vehicle"), reply_markup=InlineKeyboardMarkup(kb))

    elif data == "type_package":
        core.set_customer_state(customer["id"], "awaiting_description")
        await query.edit_message_text(core.get_msg("ask_description"), reply_markup=CANCEL_KB)

    elif data in ("vehicle_car", "vehicle_moto"):
        vehicle = core.get_msg("button_car") if data == "vehicle_car" else core.get_msg("button_moto")
        core.set_customer_field(customer["id"], "draft_vehicle", vehicle)
        core.set_customer_state(customer["id"], "awaiting_pickup")
        await query.edit_message_text(core.get_msg("ask_pickup"), reply_markup=CANCEL_KB)


CANCEL_KB = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel_flow")]])


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = str(update.effective_chat.id)
        customer = core.get_or_create_customer(chat_id, "telegram")
        state = customer["state"]
        text_body = update.message.text.strip()

        if text_body in ("الغاء", "إلغاء", "الغاء الطلب", "إلغاء الطلب", "cancel", "Cancel"):
            cancelled_code = core.cancel_customer_order(customer["id"])
            if cancelled_code:
                await update.message.reply_text(f"تم إلغاء طلبك رقم #{cancelled_code} ✅")
            else:
                await update.message.reply_text("تم إلغاء العملية الحالية.")
            return

        if state == "awaiting_pickup":
            core.set_customer_field(customer["id"], "draft_pickup", text_body)
            core.set_customer_state(customer["id"], "awaiting_dropoff")
            await update.message.reply_text(core.get_msg("ask_dropoff"), reply_markup=CANCEL_KB)

        elif state == "awaiting_dropoff":
            description = f"من {customer['draft_pickup']} إلى {text_body}"
            core.set_customer_field(customer["id"], "draft_details", description)
            core.set_customer_state(customer["id"], "awaiting_price")
            min_price = core.get_min_price("فردي")
            await update.message.reply_text(core.get_msg("ask_price", min_price=min_price), reply_markup=CANCEL_KB)

        elif state == "awaiting_description":
            core.set_customer_field(customer["id"], "draft_details", text_body)
            core.set_customer_state(customer["id"], "awaiting_price")
            min_price = core.get_min_price("طلبات")
            await update.message.reply_text(core.get_msg("ask_price", min_price=min_price), reply_markup=CANCEL_KB)

        elif state == "awaiting_price":
            try:
                price = float(text_body)
            except ValueError:
                await update.message.reply_text(core.get_msg("price_invalid"), reply_markup=CANCEL_KB)
                return
            order_type_preview = "فردي" if customer["draft_vehicle"] else "طلبات"
            min_price = core.get_min_price(order_type_preview)
            if price < min_price:
                await update.message.reply_text(core.get_msg("price_too_low", min_price=min_price), reply_markup=CANCEL_KB)
                return
            core.set_customer_field(customer["id"], "draft_price", str(price))
            core.set_customer_state(customer["id"], "awaiting_contact")
            await update.message.reply_text("اكتب رقم تليفون أو واتساب للتواصل معاك بخصوص الطلب:", reply_markup=CANCEL_KB)

        elif state == "awaiting_contact":
            contact_info = text_body
            price = float(customer["draft_price"]) if customer.get("draft_price") else core.MIN_PRICE
            order_type = "فردي" if customer["draft_vehicle"] else "طلبات"
            order_code = core.create_order(customer["id"], order_type, customer["draft_vehicle"],
                                            customer["draft_details"], price, "telegram", contact_info)
            core.set_customer_state(customer["id"], "idle")
            core.set_customer_field(customer["id"], "draft_vehicle", None)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel_flow")]])
            await update.message.reply_text(core.get_msg("order_confirmed", order_code=order_code, price=price), reply_markup=kb)
            await notify_drivers_group(context, order_code, order_type, customer["draft_details"], price)

        elif state == "awaiting_complaint_order":
            core.set_customer_field(customer["id"], "draft_details", text_body)
            core.set_customer_state(customer["id"], "awaiting_complaint_message")
            await update.message.reply_text(core.get_msg("complaint_ask_message"))

        elif state == "awaiting_complaint_message":
            order_code = core.parse_order_code(customer["draft_details"])
            core.create_complaint(customer["id"], order_code, text_body)
            core.set_customer_state(customer["id"], "idle")
            await update.message.reply_text(core.get_msg("complaint_confirmed"))

        elif state == "awaiting_rating":
            try:
                rating = int(text_body)
            except ValueError:
                await update.message.reply_text("من فضلك اكتب رقم من 1 لـ 5 بس.")
                return
            if rating < 1 or rating > 5:
                await update.message.reply_text("التقييم لازم يكون من 1 لـ 5.")
                return
            order_code = int(customer["draft_details"]) if customer.get("draft_details") else None
            if order_code:
                core.submit_rating(customer["id"], order_code, rating)
            core.set_customer_state(customer["id"], "idle")
            core.set_customer_field(customer["id"], "draft_details", None)
            await update.message.reply_text("شكرًا لتقييمك! 🙏\nلطلب جديد، ابعت أي رسالة في أي وقت.")

        else:
            active_order = core.get_customer_active_order(customer["id"])
            if active_order and active_order["status"] == "قيد التوصيل":
                await update.message.reply_text(f"جاري تنفيذ طلبك رقم #{active_order['order_code']} حاليًا، هنبلغك أول ما يخلص.")
            elif active_order and active_order["status"] == "جديد":
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel_flow")]])
                await update.message.reply_text(f"جاري عرض طلبك رقم #{active_order['order_code']} على المناديب، استنى شوية.", reply_markup=kb)
            else:
                kb = [[InlineKeyboardButton(core.get_msg("button_order"), callback_data="start_order")],
                      [InlineKeyboardButton(core.get_msg("button_complaint"), callback_data="start_complaint")]]
                await update.message.reply_text(core.get_msg("welcome_menu"), reply_markup=InlineKeyboardMarkup(kb))

    except Exception as e:
        print("خطأ في text_handler:", e)
        await update.message.reply_text("حصل خطأ، حاول تاني.")


async def group_id_helper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


def auto_cancel_loop():
    """بتشتغل في الخلفية طول الوقت، وكل دقيقة بتلغي أي طلب (من أي مصدر) عدّى عليه الوقت المسموح
    من غير ما مندوب يقبله (الوقت ده بيتحدد من لوحة الأدمن، 0 = الميزة متعطّلة)."""
    while True:
        try:
            core.auto_cancel_stale_orders()
        except Exception as e:
            print("خطأ في auto_cancel_loop:", e)
        time.sleep(60)


if __name__ == "__main__":
    threading.Thread(target=auto_cancel_loop, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("groupid", group_id_helper))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("تليجرام بوت شغال...")
    app.run_polling()