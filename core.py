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


def parse_order_code(text):
    match = re.search(r'\d+', text or "")
    return int(match.group()) if match else None


def send_message_to_customer(customer, text):
    if customer["telegram_chat_id"]:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": customer["telegram_chat_id"], "text": text}
        )
    else:
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": customer["phone"], "type": "text", "text": {"body": text}}
        requests.post(f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages", headers=headers, json=payload)


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
    conn.execute("UPDATE customers SET points = points + ? WHERE id = ?", (points_to_add, customer_id))
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


def create_order(customer_id, order_type, vehicle_type, description, price, source):
    conn = get_db()
    last = conn.execute("SELECT MAX(order_code) as m FROM orders").fetchone()
    next_code = 1000 if last["m"] is None else last["m"] + 1
    conn.execute(
        "INSERT INTO orders (order_code, customer_id, status, details, price, order_type, vehicle_type, source) VALUES (?, ?, 'جديد', ?, ?, ?, ?, ?)",
        (next_code, customer_id, description, price, order_type, vehicle_type, source)
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

    commission_percent = float(get_setting("commission_percent") or 10)
    commission = round(order["price"] * commission_percent / 100, 2)
    new_balance = driver["balance"] - commission
    locked_until = (datetime.now() + timedelta(minutes=20)).isoformat()

    conn.execute("UPDATE drivers SET balance = ?, locked_until = ?, monthly_orders_count = monthly_orders_count + 1 WHERE id = ?",
                 (new_balance, locked_until, driver["id"]))
    conn.execute("UPDATE orders SET status = 'قيد التوصيل', driver_id = ?, accepted_at = ? WHERE id = ?",
                 (driver["id"], datetime.now().isoformat(), order["id"]))
    conn.execute("UPDATE admin_wallet SET balance = balance + ? WHERE id = 1", (commission,))
    conn.commit()

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
    order = conn.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,)).fetchone()
    conn.close()
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
    new_points = customer["points"] + points_per_order

    conn.execute("UPDATE orders SET status = 'مكتملة', finished_at = ? WHERE id = ?",
                 (datetime.now().isoformat(), order["id"]))
    conn.execute("UPDATE drivers SET locked_until = NULL WHERE id = ?", (driver["id"],))
    conn.execute("UPDATE customers SET points = ? WHERE id = ?", (new_points, customer["id"]))
    conn.commit()

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer["id"],)).fetchone()
    conn.close()
    return True, get_msg("driver_finish_confirmed", order_code=order_code), order, customer, points_per_order, new_points