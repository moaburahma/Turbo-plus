import re
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

MIN_PRICE = 25
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
DATABASE_URL = os.getenv("DATABASE_URL")


class DBConnection:
    """
    Wrapper بيخلي psycopg2 يتصرف زي sqlite3.Connection اللي كان مستخدم قبل كده،
    عشان الكود القديم (execute بعلامة ? وبيرجع rows بتتقرا زي dict) يفضل شغال
    من غير ما نعدل كل استعلام سطر بسطر.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=()):
        query = query.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return DBConnection(conn)


def get_setting(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def get_msg(key, **kwargs):
    conn = get_db()
    row = conn.execute("SELECT value FROM bot_messages WHERE key = ?", (key,)).fetchone()
    conn.close()
    text = row["value"] if row else key
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def get_min_price(order_type):
    """بيرجع الحد الأدنى للسعر حسب نوع الطلب (فردي / طلبات)، قابل للتعديل من لوحة الأدمن."""
    key = "min_price_individual" if order_type == "فردي" else "min_price_packages"
    value = get_setting(key)
    try:
        return float(value) if value else MIN_PRICE
    except ValueError:
        return MIN_PRICE


def get_customer_active_order(customer_id):
    """بيرجع آخر طلب لسه شغال للعميل (جديد أو قيد التوصيل)، أو None لو مفيش."""
    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? AND status IN ('جديد', 'قيد التوصيل') ORDER BY id DESC LIMIT 1",
        (customer_id,)
    ).fetchone()
    conn.close()
    return order


def _period_bounds(period):
    """بيرجع (بداية الفترة كـ نص تاريخ، مفتاح فريد للفترة) لأنواع الفترات: daily / weekly / monthly."""
    now = datetime.now()
    if period == "daily":
        start = now.strftime("%Y-%m-%d 00:00:00")
        key = now.strftime("%Y-%m-%d")
    elif period == "weekly":
        monday = now - timedelta(days=now.weekday())
        start = monday.strftime("%Y-%m-%d 00:00:00")
        iso = now.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
    else:  # monthly
        start = now.strftime("%Y-%m-01 00:00:00")
        key = now.strftime("%Y-%m")
    return start, key


def check_and_grant_customer_reward(customer_id):
    """بتفحص لو العميل حقق عدد الطلبات المطلوب في أي فترة (يومي/أسبوعي/شهري) وتضيفله نقاط تلقائيًا، مرة واحدة بس لكل فترة."""
    for period in ("daily", "weekly", "monthly"):
        threshold = get_setting(f"reward_customer_{period}_threshold")
        reward_points = get_setting(f"reward_customer_{period}_points")
        try:
            threshold = int(threshold) if threshold else 0
            reward_points = float(reward_points) if reward_points else 0
        except ValueError:
            continue
        if threshold <= 0 or reward_points <= 0:
            continue

        start, key = _period_bounds(period)
        conn = get_db()
        count_row = conn.execute(
            "SELECT COUNT(*) as c FROM orders WHERE customer_id = ? AND status = 'مكتملة' AND finished_at >= ?",
            (customer_id, start)
        ).fetchone()
        if count_row["c"] >= threshold:
            already = conn.execute(
                "SELECT 1 FROM reward_grants WHERE target = 'customer' AND target_id = ? AND period = ? AND period_key = ?",
                (customer_id, period, key)
            ).fetchone()
            if not already:
                conn.execute("UPDATE customers SET points = ROUND((points + ?)::numeric, 2) WHERE id = ?", (reward_points, customer_id))
                conn.execute(
                    "INSERT INTO reward_grants (target, target_id, period, period_key) VALUES ('customer', ?, ?, ?)",
                    (customer_id, period, key)
                )
                conn.commit()
                customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
                try:
                    send_message_to_customer(customer, f"🎉 مبروك! وصلت لـ {threshold} طلب مكتمل، اكسبت مكافأة {reward_points} نقطة إضافية!")
                except Exception as e:
                    print("فشل إبلاغ العميل بالمكافأة:", e)
        conn.close()


def check_and_grant_driver_reward(driver_id):
    """نفس فكرة مكافأة العميل، بس للمندوب وبتضيف رصيد فلوس بدل نقاط."""
    for period in ("daily", "weekly", "monthly"):
        threshold = get_setting(f"reward_driver_{period}_threshold")
        reward_amount = get_setting(f"reward_driver_{period}_amount")
        try:
            threshold = int(threshold) if threshold else 0
            reward_amount = float(reward_amount) if reward_amount else 0
        except ValueError:
            continue
        if threshold <= 0 or reward_amount <= 0:
            continue

        start, key = _period_bounds(period)
        conn = get_db()
        count_row = conn.execute(
            "SELECT COUNT(*) as c FROM orders WHERE driver_id = ? AND status = 'مكتملة' AND finished_at >= ?",
            (driver_id, start)
        ).fetchone()
        if count_row["c"] >= threshold:
            already = conn.execute(
                "SELECT 1 FROM reward_grants WHERE target = 'driver' AND target_id = ? AND period = ? AND period_key = ?",
                (driver_id, period, key)
            ).fetchone()
            if not already:
                conn.execute("UPDATE drivers SET balance = ROUND((balance + ?)::numeric, 2) WHERE id = ?", (reward_amount, driver_id))
                conn.execute(
                    "INSERT INTO reward_grants (target, target_id, period, period_key) VALUES ('driver', ?, ?, ?)",
                    (driver_id, period, key)
                )
                conn.commit()
                driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
                try:
                    send_telegram_private_message(driver["telegram_user_id"], f"🎉 مبروك! وصلت لـ {threshold} طلب مكتمل، اكسبت مكافأة {reward_amount} جنيه إضافية على رصيدك!")
                except Exception as e:
                    print("فشل إبلاغ المندوب بالمكافأة:", e)
        conn.close()


def parse_order_code(text):
    match = re.search(r'\d+', text or "")
    return int(match.group()) if match else None


def send_message_to_customer(customer, text):
    if customer["telegram_chat_id"]:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": customer["telegram_chat_id"], "text": text}, timeout=10
        )
    else:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": customer["phone"], "type": "text", "text": {"body": text}}
        requests.post(f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages", headers=headers, json=payload, timeout=10)


def send_telegram_private_message(telegram_user_id, text):
    """بيبعت رسالة خاصة (Direct Message) لمستخدم تليجرام معيّن عن طريق الـ user id بتاعه.
    بنستخدمها عشان نبعت معلومات التواصل الخاصة بالعميل للمندوب اللي قبل الطلب بس، من غير ما تظهر في الجروب."""
    if not telegram_user_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": telegram_user_id, "text": text}, timeout=10
        )
    except Exception as e:
        print("فشل إرسال رسالة خاصة للمندوب:", e)


def get_telegram_driver_groups():
    conn = get_db()
    rows = conn.execute("SELECT * FROM telegram_groups WHERE role = 'drivers'").fetchall()
    conn.close()
    return rows


def add_telegram_group(chat_id, label):
    conn = get_db()
    conn.execute(
        "INSERT INTO telegram_groups (chat_id, label, role) VALUES (?, ?, 'drivers') ON CONFLICT (chat_id) DO NOTHING",
        (chat_id, label)
    )
    conn.commit()
    conn.close()


def delete_telegram_group(group_id):
    conn = get_db()
    conn.execute("DELETE FROM telegram_groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()


def get_or_create_customer(identifier, platform):
    conn = get_db()
    if platform == "telegram":
        customer = conn.execute("SELECT * FROM customers WHERE telegram_chat_id = ?", (identifier,)).fetchone()
        if customer is None:
            phone_placeholder = f"tg:{identifier}"
            conn.execute(
                "INSERT INTO customers (phone, telegram_chat_id, state, points) VALUES (?, ?, 'idle', 0)",
                (phone_placeholder, identifier)
            )
            conn.commit()
            customer = conn.execute("SELECT * FROM customers WHERE telegram_chat_id = ?", (identifier,)).fetchone()
    else:
        customer = conn.execute("SELECT * FROM customers WHERE phone = ?", (identifier,)).fetchone()
        if customer is None:
            conn.execute("INSERT INTO customers (phone, state, points) VALUES (?, 'idle', 0)", (identifier,))
            conn.commit()
            customer = conn.execute("SELECT * FROM customers WHERE phone = ?", (identifier,)).fetchone()
    conn.close()
    return customer


def set_customer_state(customer_id, state):
    conn = get_db()
    conn.execute("UPDATE customers SET state = ? WHERE id = ?", (state, customer_id))
    conn.commit()
    conn.close()


def set_customer_field(customer_id, field, value):
    conn = get_db()
    conn.execute(f"UPDATE customers SET {field} = ? WHERE id = ?", (value, customer_id))
    conn.commit()
    conn.close()


def add_customer_points(customer_id, points_to_add):
    conn = get_db()
    conn.execute("UPDATE customers SET points = ROUND((points + ?)::numeric, 2) WHERE id = ?", (points_to_add, customer_id))
    conn.commit()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    conn.close()
    return customer


def get_driver_by_telegram_id(telegram_user_id):
    conn = get_db()
    driver = conn.execute("SELECT * FROM drivers WHERE telegram_user_id = ?", (str(telegram_user_id),)).fetchone()
    conn.close()
    return driver


def get_driver_by_id(driver_id):
    conn = get_db()
    driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    conn.close()
    return driver


def create_order(customer_id, order_type, vehicle_type, description, price, source, contact_info=None):
    conn = get_db()
    last = conn.execute("SELECT MAX(order_code) as m FROM orders").fetchone()
    next_code = 1000 if last["m"] is None else last["m"] + 1
    conn.execute(
        "INSERT INTO orders (order_code, customer_id, status, details, price, order_type, vehicle_type, source, contact_info) VALUES (?, ?, 'جديد', ?, ?, ?, ?, ?, ?)",
        (next_code, customer_id, description, price, order_type, vehicle_type, source, contact_info)
    )
    conn.commit()
    conn.close()
    return next_code


def create_complaint(customer_id, order_code, message):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,)).fetchone()
    conn.execute(
        "INSERT INTO complaints (order_id, customer_id, driver_id, message, status) VALUES (?, ?, ?, ?, 'جديدة')",
        (order["id"] if order else None, customer_id, order["driver_id"] if order else None, message)
    )
    conn.commit()
    conn.close()


def accept_order(driver_id, order_code):
    conn = get_db()
    driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    order = conn.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,)).fetchone()

    if driver is None or order is None:
        conn.close()
        return False, "الطلب أو المندوب مش موجود.", None, None, None

    if order["status"] != "جديد":
        conn.close()
        return False, get_msg("driver_order_taken"), order, None, driver

    if driver["balance"] <= 0:
        conn.close()
        return False, get_msg("driver_low_balance"), order, None, driver

    # التأكد من الفارق الزمني المطلوب بين قبول طلب والتاني (قابل للتعديل من لوحة الأدمن)
    cooldown_minutes = float(get_setting("driver_accept_cooldown_minutes") or 0)
    if cooldown_minutes > 0 and driver["locked_until"]:
        try:
            locked_until_dt = datetime.fromisoformat(driver["locked_until"])
            if datetime.now() < locked_until_dt:
                remaining = int((locked_until_dt - datetime.now()).total_seconds() / 60) + 1
                conn.close()
                return False, f"لازم تستنى {remaining} دقيقة تقريبًا قبل ما تقدر تقبل طلب جديد.", order, None, driver
        except (ValueError, TypeError):
            pass

    commission_percent = float(get_setting("commission_percent") or 10)
    commission = round(order["price"] * commission_percent / 100, 2)
    new_balance = round(driver["balance"] - commission, 2)
    next_allowed_accept = (datetime.now() + timedelta(minutes=cooldown_minutes)).isoformat() if cooldown_minutes > 0 else None

    conn.execute("UPDATE drivers SET balance = ?, locked_until = ?, monthly_orders_count = monthly_orders_count + 1 WHERE id = ?",
                 (new_balance, next_allowed_accept, driver["id"]))
    conn.execute("UPDATE orders SET status = 'قيد التوصيل', driver_id = ?, accepted_at = ? WHERE id = ?",
                 (driver["id"], datetime.now().isoformat(), order["id"]))
    conn.execute("UPDATE admin_wallet SET balance = ROUND((balance + ?)::numeric, 2) WHERE id = 1", (commission,))
    conn.commit()

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
    order = conn.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,)).fetchone()
    conn.close()

    # نبلّغ العميل إن طلبه اتقبل، وباسم ورقم المندوب
    try:
        send_message_to_customer(
            customer,
            f"تم قبول طلبك رقم #{order_code} ✅\nالمندوب: {driver['name']}\nرقم تليفونه: {driver['phone']}"
        )
    except Exception as e:
        print("فشل إبلاغ العميل بقبول الطلب:", e)

    return True, get_msg("driver_accept_confirmed", order_code=order_code, customer_phone=customer["phone"]), order, customer, driver


def finish_order(driver_id, order_code):
    """يرجع (ok, msg, order, customer, points_earned, new_points)"""
    conn = get_db()
    driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    order = conn.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,)).fetchone()

    if driver is None or order is None or order["driver_id"] != driver_id:
        conn.close()
        return False, "مش انت اللي قابل الطلب ده.", None, None, None, None

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
    points_per_order = float(get_setting("points_per_order") or 1)
    new_points = round(customer["points"] + points_per_order, 2)

    conn.execute("UPDATE orders SET status = 'مكتملة', finished_at = ? WHERE id = ?",
                 (datetime.now().isoformat(), order["id"]))
    conn.execute("UPDATE customers SET points = ? WHERE id = ?", (new_points, customer["id"]))
    conn.commit()

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer["id"],)).fetchone()
    conn.close()

    # نبلّغ العميل إن طلبه اتسلّم، ونطلب منه يقيّم المندوب
    try:
        send_message_to_customer(
            customer,
            f"تم تسليم طلبك رقم #{order_code} بنجاح ✅\nكسبت {points_per_order} نقطة، رصيدك الحالي: {new_points} نقطة.\n"
            f"قيّم تجربتك مع المندوب من 1 لـ 5 (اكتب رقم بس):"
        )
        set_customer_state(customer["id"], "awaiting_rating")
        set_customer_field(customer["id"], "draft_details", str(order_code))
    except Exception as e:
        print("فشل إبلاغ العميل بإنهاء الطلب:", e)

    # نفحص لو العميل والمندوب استاهلوا مكافأة تلقائية
    try:
        check_and_grant_customer_reward(customer["id"])
        check_and_grant_driver_reward(driver_id)
    except Exception as e:
        print("فشل فحص المكافآت التلقائية:", e)

    return True, get_msg("driver_finish_confirmed", order_code=order_code), order, customer, points_per_order, new_points


def submit_rating(customer_id, order_code, rating):
    """بيحفظ تقييم المندوب (1-5) اللي كتبه العميل بعد انتهاء الطلب."""
    conn = get_db()
    conn.execute("UPDATE orders SET rating = ? WHERE order_code = ? AND customer_id = ?", (rating, order_code, customer_id))
    conn.commit()
    conn.close()


def cancel_customer_order(customer_id):
    """بيلغي آخر طلب 'جديد' (لسه محدش قبله) للعميل، وبيصفّر حالته لـ idle.
    بيرجع كود الطلب اللي اتلغى، أو None لو مفيش طلب قيد الانتظار أصلاً."""
    conn = get_db()
    order = conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? AND status = 'جديد' ORDER BY id DESC LIMIT 1",
        (customer_id,)
    ).fetchone()
    cancelled_order_code = None
    if order:
        conn.execute("UPDATE orders SET status = 'ملغاة' WHERE id = ?", (order["id"],))
        cancelled_order_code = order["order_code"]
    conn.execute(
        "UPDATE customers SET state = 'idle', draft_details = ?, draft_vehicle = ?, draft_pickup = ?, draft_price = ? WHERE id = ?",
        (None, None, None, None, customer_id)
    )
    conn.commit()
    conn.close()
    return cancelled_order_code


def auto_cancel_stale_orders():
    """بتدور على أي طلب لسه 'جديد' (محدش قبله) وعدّى عليه الوقت المسموح، وتلغيه تلقائيًا وتبلغ العميل.
    الوقت المسموح قابل للتعديل من لوحة الأدمن (إعداد order_auto_cancel_minutes)، 0 = الميزة متعطّلة."""
    minutes_setting = get_setting("order_auto_cancel_minutes")
    try:
        minutes = float(minutes_setting) if minutes_setting else 0
    except ValueError:
        minutes = 0
    if minutes <= 0:
        return

    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    stale_orders = conn.execute(
        "SELECT * FROM orders WHERE status = 'جديد' AND created_at < ?", (cutoff,)
    ).fetchall()
    for order in stale_orders:
        conn.execute("UPDATE orders SET status = 'ملغاة' WHERE id = ?", (order["id"],))
    conn.commit()
    conn.close()

    for order in stale_orders:
        conn2 = get_db()
        customer = conn2.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
        conn2.execute("UPDATE customers SET state = 'idle' WHERE id = ?", (order["customer_id"],))
        conn2.commit()
        conn2.close()
        if customer:
            try:
                send_message_to_customer(
                    customer,
                    f"تم إلغاء طلبك رقم #{order['order_code']} تلقائيًا لعدم توفر مندوب حاليًا، برجاء المحاولة مرة أخرى."
                )
            except Exception as e:
                print("فشل إبلاغ العميل بالإلغاء التلقائي:", e)