from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import json
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
from whatsapp_webhook import whatsapp_bp

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key-later")
app.register_blueprint(whatsapp_bp)


DATABASE_URL = os.getenv("DATABASE_URL")

# كل صلاحية ممكن تتحدد لموظف: المفتاح اللي بيتخزن في عمود permissions (JSON)، والاسم اللي بيظهر في اللوحة
PERMISSION_KEYS = [
    "orders_view", "orders_edit", "orders_delete",
    "drivers_view", "drivers_manage", "drivers_balance", "drivers_delete",
    "complaints_view", "complaints_reply",
    "customers_view", "customers_points", "customers_delete",
    "reports_view",
    "settings_view",
    "telegram_groups_view",
    "messages_view",
    "broadcast_send",
]
PERMISSION_LABELS = {
    "orders_view": "عرض صفحة الطلبات",
    "orders_edit": "تعديل حالة الطلب",
    "orders_delete": "حذف الطلبات",
    "drivers_view": "عرض صفحة المناديب",
    "drivers_manage": "إضافة/حظر مناديب وتعديل بياناتهم",
    "drivers_balance": "شحن رصيد المناديب",
    "drivers_delete": "حذف المناديب",
    "complaints_view": "عرض صفحة الشكاوى",
    "complaints_reply": "الرد على الشكاوى",
    "customers_view": "عرض صفحة العملاء",
    "customers_points": "إضافة نقاط للعملاء",
    "customers_delete": "حذف العملاء",
    "reports_view": "عرض التقارير",
    "settings_view": "الإعدادات العامة (عمولة، حدود سعر، رصيد الشركة...)",
    "telegram_groups_view": "إدارة جروبات تليجرام",
    "messages_view": "تعديل نصوص البوت",
    "broadcast_send": "إرسال رسائل جماعية للعملاء",
}


class DBConnection:
    """نفس الـ wrapper المستخدم في core.py عشان نفس أسلوب conn.execute("...?...") يفضل شغال."""

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


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def permission_required(perm_key):
    """زي login_required، بس كمان بتتأكد إن الأدمن (لو مش الأدمن الرئيسي) عنده الصلاحية دي بالتحديد."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("admin_id"):
                return redirect(url_for("login"))
            if session.get("is_main_admin"):
                return f(*args, **kwargs)
            perms = session.get("permissions", {})
            if not perms.get(perm_key):
                flash("مفيش عندك صلاحية توصل للصفحة دي، كلم الأدمن الرئيسي.")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def has_permission(perm_key):
    """بتتستخدم جوه القوالب أو الكود عشان نتأكد من صلاحية معيّنة من غير ما نمنع الوصول للصفحة كلها."""
    if session.get("is_main_admin"):
        return True
    return bool(session.get("permissions", {}).get(perm_key))


app.jinja_env.globals["has_permission"] = has_permission


def driver_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("driver_id"):
            return redirect(url_for("driver_login"))
        return f(*args, **kwargs)
    return wrapper


# ============ تسجيل دخول الأدمن ============
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        admin = conn.execute("SELECT * FROM admin_users WHERE username = ?", (request.form["username"],)).fetchone()
        conn.close()
        if admin and check_password_hash(admin["password_hash"], request.form["password"]):
            session.clear()
            session["admin_id"] = admin["id"]
            session["is_main_admin"] = bool(admin["is_main_admin"])
            try:
                session["permissions"] = json.loads(admin["permissions"] or "{}")
            except (json.JSONDecodeError, TypeError):
                session["permissions"] = {}
            return redirect(url_for("dashboard"))
        flash("اسم المستخدم أو كلمة المرور غلط")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "new": conn.execute("SELECT COUNT(*) c FROM orders WHERE status='جديد'").fetchone()["c"],
        "in_delivery": conn.execute("SELECT COUNT(*) c FROM orders WHERE status='قيد التوصيل'").fetchone()["c"],
        "completed": conn.execute("SELECT COUNT(*) c FROM orders WHERE status='مكتملة'").fetchone()["c"],
        "cancelled": conn.execute("SELECT COUNT(*) c FROM orders WHERE status='ملغاة'").fetchone()["c"],
        "complaints": conn.execute("SELECT COUNT(*) c FROM complaints").fetchone()["c"],
    }
    recent_orders = conn.execute("""
        SELECT orders.order_code, orders.status, orders.price, orders.details, customers.phone as customer_phone
        FROM orders LEFT JOIN customers ON orders.customer_id = customers.id
        ORDER BY orders.id DESC LIMIT 10
    """).fetchall()
    admin_wallet = conn.execute("SELECT balance FROM admin_wallet WHERE id = 1").fetchone()
    conn.close()
    return render_template("dashboard.html", stats=stats, recent_orders=recent_orders,
                           admin_balance=admin_wallet["balance"] if admin_wallet else 0)


@app.route("/orders")
@permission_required("orders_view")
def orders():
    search = request.args.get("q", "")
    conn = get_db()
    query = """SELECT orders.*, customers.phone as customer_phone, drivers.name as driver_name
               FROM orders
               LEFT JOIN customers ON orders.customer_id = customers.id
               LEFT JOIN drivers ON orders.driver_id = drivers.id"""
    if search:
        rows = conn.execute(query + " WHERE CAST(orders.order_code AS TEXT) LIKE ? ORDER BY orders.id DESC",
                             (f"%{search}%",)).fetchall()
    else:
        rows = conn.execute(query + " ORDER BY orders.id DESC").fetchall()
    conn.close()
    return render_template("orders.html", orders=rows, search=search)


@app.route("/orders/<int:order_id>/delete", methods=["POST"])
@permission_required("orders_delete")
def delete_order(order_id):
    conn = get_db()
    # نفصل أي شكاوى مرتبطة بالطلب ده الأول عشان الحذف ميعملش مشكلة في القيود بين الجداول
    conn.execute("UPDATE complaints SET order_id = NULL WHERE order_id = ?", (order_id,))
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    flash("تم حذف الطلب")
    return redirect(url_for("orders"))


@app.route("/orders/<int:order_id>/status", methods=["POST"])
@permission_required("orders_edit")
def update_order_status(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (request.form["status"], order_id))
    conn.commit()
    conn.close()
    return redirect(url_for("orders"))


# ============ إدارة المناديب ============
@app.route("/drivers")
@permission_required("drivers_view")
def drivers():
    search = request.args.get("q", "")
    min_orders = request.args.get("min_orders", "")
    period = request.args.get("period", "all")
    specific_month = request.args.get("specific_month", "")
    start, end, period = compute_period_range(period, specific_month)

    conn = get_db()
    query = """
        SELECT drivers.*,
               COUNT(orders.id) FILTER (WHERE orders.status = 'مكتملة' AND orders.finished_at >= ? AND orders.finished_at < ?) as period_order_count
        FROM drivers
        LEFT JOIN orders ON orders.driver_id = drivers.id
        WHERE 1=1
    """
    params = [start, end]
    if search:
        query += " AND (drivers.name ILIKE ? OR drivers.phone ILIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    query += " GROUP BY drivers.id"
    if min_orders:
        try:
            query += " HAVING COUNT(orders.id) FILTER (WHERE orders.status = 'مكتملة' AND orders.finished_at >= ? AND orders.finished_at < ?) >= ?"
            params += [start, end, int(min_orders)]
        except ValueError:
            pass
    query += " ORDER BY drivers.id DESC"
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return render_template("drivers.html", drivers=rows, search=search, min_orders=min_orders,
                           period=period, specific_month=specific_month)


@app.route("/drivers/add", methods=["POST"])
@permission_required("drivers_manage")
def add_driver():
    conn = get_db()
    conn.execute(
        "INSERT INTO drivers (phone, name, balance, is_active, is_blocked, password_hash, telegram_user_id) VALUES (?, ?, 0, 1, 0, ?, ?)",
        (request.form["phone"], request.form["name"], generate_password_hash(request.form["password"]),
         request.form.get("telegram_user_id") or None)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("drivers"))

@app.route("/drivers/<int:driver_id>/update", methods=["POST"])
@login_required
def update_driver(driver_id):
    action = request.form["action"]
    if action == "add_balance" and not has_permission("drivers_balance"):
        flash("مفيش عندك صلاحية شحن رصيد المناديب.")
        return redirect(url_for("drivers"))
    if action in ("block", "unblock") and not has_permission("drivers_manage"):
        flash("مفيش عندك صلاحية حظر/فك حظر المناديب.")
        return redirect(url_for("drivers"))
    conn = get_db()
    if action == "block":
        conn.execute("UPDATE drivers SET is_blocked = 1 WHERE id = ?", (driver_id,))
    elif action == "unblock":
        conn.execute("UPDATE drivers SET is_blocked = 0 WHERE id = ?", (driver_id,))
    elif action == "add_balance":
        conn.execute("UPDATE drivers SET balance = ROUND((balance + ?)::numeric, 2) WHERE id = ?", (float(request.form["amount"]), driver_id))
    conn.commit()
    conn.close()
    return redirect(url_for("drivers"))


# ============ الإعدادات ============
@app.route("/drivers/<int:driver_id>/delete", methods=["POST"])
@permission_required("drivers_delete")
def delete_driver(driver_id):
    conn = get_db()
    # نفصل المندوب عن أي طلبات قديمة بتاعته الأول عشان منكسرش القيود بين الجداول
    conn.execute("UPDATE orders SET driver_id = NULL WHERE driver_id = ?", (driver_id,))
    conn.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
    conn.commit()
    conn.close()
    flash("تم حذف المندوب")
    return redirect(url_for("drivers"))


@app.route("/drivers/<int:driver_id>/set_telegram_id", methods=["POST"])
@permission_required("drivers_manage")
def update_driver_telegram_id(driver_id):
    conn = get_db()
    conn.execute("UPDATE drivers SET telegram_user_id = ? WHERE id = ?",
                 (request.form["telegram_user_id"] or None, driver_id))
    conn.commit()
    conn.close()
    flash("تم تحديث Telegram ID للمندوب")
    return redirect(url_for("drivers"))


@app.route("/settings", methods=["GET", "POST"])
@permission_required("settings_view")
def settings():
    conn = get_db()
    if request.method == "POST":
        if "commission_percent" in request.form:
            conn.execute("UPDATE settings SET value = ? WHERE key = 'commission_percent'", (request.form["commission_percent"],))
            conn.execute("UPDATE settings SET value = ? WHERE key = 'points_per_order'", (request.form["points_per_order"],))
            individual = "1" if request.form.get("individual_enabled") == "on" else "0"
            packages = "1" if request.form.get("packages_enabled") == "on" else "0"
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('individual_enabled', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (individual,))
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('packages_enabled', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (packages,))
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('min_price_individual', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (request.form.get("min_price_individual", "25"),))
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('min_price_packages', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (request.form.get("min_price_packages", "25"),))
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('driver_accept_cooldown_minutes', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (request.form.get("driver_accept_cooldown_minutes", "0"),))
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('order_auto_cancel_minutes', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (request.form.get("order_auto_cancel_minutes", "0"),))
            reward_keys = [
                "reward_customer_daily_threshold", "reward_customer_daily_points",
                "reward_customer_weekly_threshold", "reward_customer_weekly_points",
                "reward_customer_monthly_threshold", "reward_customer_monthly_points",
                "reward_driver_daily_threshold", "reward_driver_daily_amount",
                "reward_driver_weekly_threshold", "reward_driver_weekly_amount",
                "reward_driver_monthly_threshold", "reward_driver_monthly_amount",
            ]
            for key in reward_keys:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (key, request.form.get(key, "0"))
                )
            conn.commit()
            flash("تم حفظ الإعدادات")

        elif "wallet_amount" in request.form:
            amount = float(request.form["wallet_amount"])
            action = request.form.get("wallet_action", "add")
            delta = amount if action == "add" else -amount
            conn.execute("UPDATE admin_wallet SET balance = ROUND((balance + ?)::numeric, 2) WHERE id = 1", (delta,))
            conn.commit()
            flash("تم تحديث رصيد الشركة")

        elif "new_username" in request.form:
            admin = conn.execute("SELECT * FROM admin_users WHERE id = ?", (session["admin_id"],)).fetchone()
            if check_password_hash(admin["password_hash"], request.form["current_password"]):
                conn.execute("UPDATE admin_users SET username = ?, password_hash = ? WHERE id = ?",
                             (request.form["new_username"], generate_password_hash(request.form["new_password"]), session["admin_id"]))
                conn.commit()
                flash("تم تحديث بيانات الدخول، سجّل دخول تاني بالبيانات الجديدة")
                session.clear()
                return redirect(url_for("login"))
            else:
                flash("كلمة المرور الحالية غلط")

    def setting_value(key, default):
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    commission = setting_value("commission_percent", "10")
    points = setting_value("points_per_order", "1")
    individual_enabled = setting_value("individual_enabled", "0")
    packages_enabled = setting_value("packages_enabled", "1")
    min_price_individual = setting_value("min_price_individual", "25")
    min_price_packages = setting_value("min_price_packages", "25")
    driver_accept_cooldown_minutes = setting_value("driver_accept_cooldown_minutes", "0")
    order_auto_cancel_minutes = setting_value("order_auto_cancel_minutes", "0")
    reward_values = {key: setting_value(key, "0") for key in [
        "reward_customer_daily_threshold", "reward_customer_daily_points",
        "reward_customer_weekly_threshold", "reward_customer_weekly_points",
        "reward_customer_monthly_threshold", "reward_customer_monthly_points",
        "reward_driver_daily_threshold", "reward_driver_daily_amount",
        "reward_driver_weekly_threshold", "reward_driver_weekly_amount",
        "reward_driver_monthly_threshold", "reward_driver_monthly_amount",
    ]}
    wallet_row = conn.execute("SELECT balance FROM admin_wallet WHERE id = 1").fetchone()
    wallet_balance = round(wallet_row["balance"], 2) if wallet_row else 0
    conn.close()
    return render_template(
        "settings.html", commission=commission, points=points,
        individual_enabled=individual_enabled, packages_enabled=packages_enabled,
        min_price_individual=min_price_individual, min_price_packages=min_price_packages,
        driver_accept_cooldown_minutes=driver_accept_cooldown_minutes, wallet_balance=wallet_balance,
        order_auto_cancel_minutes=order_auto_cancel_minutes,
        reward=reward_values
    )

# ============ نصوص البوت ============
@app.route("/messages")
@permission_required("messages_view")
def messages():
    conn = get_db()
    rows = conn.execute("SELECT * FROM bot_messages ORDER BY key").fetchall()
    conn.close()
    return render_template("messages.html", messages=rows)


@app.route("/messages/update", methods=["POST"])
@permission_required("messages_view")
def update_messages():
    conn = get_db()
    for key in request.form:
        conn.execute("UPDATE bot_messages SET value = ? WHERE key = ?", (request.form[key], key))
    conn.commit()
    conn.close()
    return redirect(url_for("messages"))


# ============ الشكاوى ============
@app.route("/complaints")
@permission_required("complaints_view")
def complaints():
    conn = get_db()
    rows = conn.execute("""
        SELECT complaints.*, customers.phone as customer_phone
        FROM complaints LEFT JOIN customers ON complaints.customer_id = customers.id
        ORDER BY complaints.id DESC
    """).fetchall()
    conn.close()
    return render_template("complaints.html", complaints=rows)


# ============ لوحة تحكم المندوب (منفصلة تمامًا) ============
@app.route("/driver/login", methods=["GET", "POST"])
def driver_login():
    if request.method == "POST":
        conn = get_db()
        driver = conn.execute("SELECT * FROM drivers WHERE phone = ?", (request.form["phone"],)).fetchone()
        conn.close()
        if driver and driver["password_hash"] and check_password_hash(driver["password_hash"], request.form["password"]):
            session.clear()
            session["driver_id"] = driver["id"]
            return redirect(url_for("driver_dashboard"))
        flash("رقم الهاتف أو كلمة المرور غلط")
    return render_template("driver_login.html")


@app.route("/driver/logout")
def driver_logout():
    session.clear()
    return redirect(url_for("driver_login"))


@app.route("/driver")
@driver_login_required
def driver_dashboard():
    conn = get_db()
    driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (session["driver_id"],)).fetchone()
    my_orders = conn.execute("SELECT * FROM orders WHERE driver_id = ? ORDER BY id DESC", (driver["id"],)).fetchall()
    available = conn.execute("SELECT * FROM orders WHERE status = 'جديد' ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("driver_dashboard.html", driver=driver, orders=my_orders, available_orders=available)


@app.route("/available-orders")
@driver_login_required
def available_orders():
    # الصفحة القديمة اتدمجت في لوحة المندوب نفسها عشان مايلخبطش، بنوجّهه هناك تلقائيًا
    return redirect(url_for("driver_dashboard"))


@app.route("/available-orders-old")
@driver_login_required
def available_orders_old():
    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE status = 'جديد' ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("available_orders.html", orders=rows)


@app.route("/available-orders/<int:order_code>/claim", methods=["POST"])
@driver_login_required
def claim_order(order_code):
    import core
    ok, msg, order, customer, driver = core.accept_order(session["driver_id"], order_code)
    flash(msg if not ok else f"تم قبول الطلب #{order_code} بنجاح")
    return redirect(url_for("available_orders"))


@app.route("/driver/orders/<int:order_code>/finish", methods=["POST"])
@driver_login_required
def driver_finish_order(order_code):
    import core
    ok, msg, order, customer, points_earned, new_points = core.finish_order(session["driver_id"], order_code)
    flash(msg if not ok else f"تم إنهاء الطلب #{order_code}")
    return redirect(url_for("driver_dashboard"))

@app.route("/complaints/<int:complaint_id>/reply", methods=["POST"])
@permission_required("complaints_reply")
def reply_complaint(complaint_id):
    import core
    conn = get_db()
    complaint = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (complaint["customer_id"],)).fetchone()
    core.send_message_to_customer(customer, request.form["reply"])
    conn.execute("UPDATE complaints SET status = 'تم الرد' WHERE id = ?", (complaint_id,))
    conn.commit()
    conn.close()
    flash("تم إرسال الرد للعميل")
    return redirect(url_for("complaints"))

@app.route("/telegram-groups")
@permission_required("telegram_groups_view")
def telegram_groups():
    conn = get_db()
    rows = conn.execute("SELECT * FROM telegram_groups").fetchall()
    conn.close()
    return render_template("telegram_groups.html", groups=rows)


@app.route("/telegram-groups/add", methods=["POST"])
@permission_required("telegram_groups_view")
def add_telegram_group():
    conn = get_db()
    conn.execute(
        "INSERT INTO telegram_groups (chat_id, label, role) VALUES (?, ?, 'drivers') ON CONFLICT (chat_id) DO NOTHING",
        (request.form["chat_id"], request.form["label"])
    )
    conn.commit()
    conn.close()
    return redirect(url_for("telegram_groups"))


@app.route("/telegram-groups/<int:group_id>/delete", methods=["POST"])
@permission_required("telegram_groups_view")
def delete_telegram_group(group_id):
    conn = get_db()
    conn.execute("DELETE FROM telegram_groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("telegram_groups"))

def compute_period_range(period, specific_month=""):
    """بيرجع (start, end, period) كنصوص تاريخ جاهزة للمقارنة مع أعمدة created_at النصية."""
    now = datetime.now()
    if period == "day":
        start = now.strftime("%Y-%m-%d 00:00:00")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    elif period == "week":
        days_since_saturday = (now.weekday() - 5) % 7  # الأسبوع عندنا يبدأ يوم السبت
        saturday = now - timedelta(days=days_since_saturday)
        start = saturday.strftime("%Y-%m-%d 00:00:00")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    elif period == "year":
        start = now.strftime("%Y-01-01 00:00:00")
        end = (now.replace(year=now.year + 1)).strftime("%Y-01-01 00:00:00")
    elif period == "specific_month" and specific_month:
        try:
            year, month = specific_month.split("-")
            year, month = int(year), int(month)
            start = f"{year:04d}-{month:02d}-01 00:00:00"
            if month == 12:
                end = f"{year + 1:04d}-01-01 00:00:00"
            else:
                end = f"{year:04d}-{month + 1:02d}-01 00:00:00"
        except (ValueError, IndexError):
            period = "month"
            start = now.strftime("%Y-%m-01 00:00:00")
            end = (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    elif period == "all":
        start = "1970-01-01 00:00:00"
        end = "9999-12-31 00:00:00"
    else:
        period = "month"
        start = now.strftime("%Y-%m-01 00:00:00")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    return start, end, period


@app.route("/reports")
@permission_required("reports_view")
def reports():
    target = request.args.get("target", "drivers")  # drivers أو customers
    period = request.args.get("period", "month")  # day / week / month / year / specific_month
    specific_month = request.args.get("specific_month", "")  # شكلها YYYY-MM
    search = request.args.get("q", "")
    min_orders = request.args.get("min_orders", "")

    start, end, period = compute_period_range(period, specific_month)

    conn = get_db()
    params = [start, end]

    if target == "customers":
        query = """
            SELECT customers.id, customers.phone, customers.points,
                   COUNT(orders.id) as order_count,
                   COALESCE(SUM(orders.price), 0) as total_price
            FROM customers
            LEFT JOIN orders ON orders.customer_id = customers.id
                AND orders.created_at >= ? AND orders.created_at < ?
            WHERE 1=1
        """
        if search:
            query += " AND customers.phone ILIKE ?"
            params.append(f"%{search}%")
        query += " GROUP BY customers.id"
        if min_orders:
            try:
                query += " HAVING COUNT(orders.id) >= ?"
                params.append(int(min_orders))
            except ValueError:
                pass
        query += " ORDER BY order_count DESC, total_price DESC"
    else:
        target = "drivers"
        query = """
            SELECT drivers.id, drivers.name, drivers.phone, drivers.balance,
                   COUNT(orders.id) as order_count,
                   COALESCE(SUM(orders.price), 0) as total_price
            FROM drivers
            LEFT JOIN orders ON orders.driver_id = drivers.id
                AND orders.created_at >= ? AND orders.created_at < ?
                AND orders.status = 'مكتملة'
            WHERE 1=1
        """
        if search:
            query += " AND (drivers.name ILIKE ? OR drivers.phone ILIKE ?)"
            params += [f"%{search}%", f"%{search}%"]
        query += " GROUP BY drivers.id"
        if min_orders:
            try:
                query += " HAVING COUNT(orders.id) >= ?"
                params.append(int(min_orders))
            except ValueError:
                pass
        query += " ORDER BY order_count DESC, total_price DESC"

    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return render_template("reports.html", rows=rows, target=target, period=period,
                           specific_month=specific_month, search=search, min_orders=min_orders)


@app.route("/customers")
@permission_required("customers_view")
def customers():
    search = request.args.get("q", "")
    min_orders = request.args.get("min_orders", "")
    period = request.args.get("period", "all")
    specific_month = request.args.get("specific_month", "")
    start, end, period = compute_period_range(period, specific_month)

    conn = get_db()
    query = """SELECT customers.*,
                      COUNT(orders.id) FILTER (WHERE orders.created_at >= ? AND orders.created_at < ?) as order_count
               FROM customers LEFT JOIN orders ON orders.customer_id = customers.id
               WHERE 1=1"""
    params = [start, end]
    if search:
        query += " AND customers.phone ILIKE ?"
        params.append(f"%{search}%")
    query += " GROUP BY customers.id"
    if min_orders:
        try:
            query += " HAVING COUNT(orders.id) FILTER (WHERE orders.created_at >= ? AND orders.created_at < ?) >= ?"
            params += [start, end, int(min_orders)]
        except ValueError:
            pass
    query += " ORDER BY customers.id DESC"
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return render_template("customers.html", customers=rows, search=search, min_orders=min_orders,
                           period=period, specific_month=specific_month)


@app.route("/customers/<int:customer_id>/delete", methods=["POST"])
@permission_required("customers_delete")
def delete_customer(customer_id):
    conn = get_db()
    # نحذف الشكاوى والطلبات المرتبطة بالعميل الأول عشان الحذف ميعملش مشكلة في القيود بين الجداول
    conn.execute("DELETE FROM complaints WHERE customer_id = ?", (customer_id,))
    conn.execute("DELETE FROM orders WHERE customer_id = ?", (customer_id,))
    conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    conn.commit()
    conn.close()
    flash("تم حذف العميل وكل طلباته")
    return redirect(url_for("customers"))


@app.route("/customers/<int:customer_id>/add_points", methods=["POST"])
@permission_required("customers_points")
def add_customer_points(customer_id):
    import core
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    conn.close()
    points_to_add = float(request.form["points"])
    updated_customer = core.add_customer_points(customer_id, points_to_add)
    core.send_message_to_customer(updated_customer, core.get_msg("points_update", points_earned=points_to_add, points_balance=updated_customer["points"]))
    flash("تم إضافة النقاط وإبلاغ العميل")
    return redirect(url_for("customers"))
@app.route("/drivers/<int:driver_id>/set_password", methods=["POST"])
@permission_required("drivers_manage")
def set_driver_password(driver_id):
    conn = get_db()
    conn.execute("UPDATE drivers SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(request.form["new_password"]), driver_id))
    conn.commit()
    conn.close()
    flash("تم تحديث كلمة مرور المندوب")
    return redirect(url_for("drivers"))


# ============ إدارة الموظفين والصلاحيات (للأدمن الرئيسي بس) ============
def main_admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login"))
        if not session.get("is_main_admin"):
            flash("الصفحة دي للأدمن الرئيسي بس.")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/staff")
@main_admin_required
def staff():
    conn = get_db()
    rows = conn.execute("SELECT * FROM admin_users ORDER BY id").fetchall()
    conn.close()
    staff_list = []
    for row in rows:
        try:
            perms = json.loads(row["permissions"] or "{}")
        except (json.JSONDecodeError, TypeError):
            perms = {}
        staff_list.append({**row, "perms": perms})
    return render_template("staff.html", staff=staff_list, permission_keys=PERMISSION_KEYS, permission_labels=PERMISSION_LABELS)


@app.route("/staff/add", methods=["POST"])
@main_admin_required
def add_staff():
    perms_json = json.dumps({k: bool(request.form.get(k)) for k in PERMISSION_KEYS})
    conn = get_db()
    existing = conn.execute("SELECT id FROM admin_users WHERE username = ?", (request.form["username"],)).fetchone()
    if existing:
        flash("اسم المستخدم ده مستخدم بالفعل")
        conn.close()
        return redirect(url_for("staff"))
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, permissions, is_main_admin) VALUES (?, ?, ?, 0)",
        (request.form["username"], generate_password_hash(request.form["password"]), perms_json)
    )
    conn.commit()
    conn.close()
    flash("تم إضافة الموظف بنجاح")
    return redirect(url_for("staff"))


@app.route("/staff/<int:staff_id>/update_permissions", methods=["POST"])
@main_admin_required
def update_staff_permissions(staff_id):
    perms_json = json.dumps({k: bool(request.form.get(k)) for k in PERMISSION_KEYS})
    conn = get_db()
    conn.execute("UPDATE admin_users SET permissions = ? WHERE id = ?", (perms_json, staff_id))
    conn.commit()
    conn.close()
    flash("تم تحديث صلاحيات الموظف")
    return redirect(url_for("staff"))


@app.route("/staff/<int:staff_id>/delete", methods=["POST"])
@main_admin_required
def delete_staff(staff_id):
    conn = get_db()
    target = conn.execute("SELECT * FROM admin_users WHERE id = ?", (staff_id,)).fetchone()
    if target and target["is_main_admin"]:
        flash("مينفعش تحذفي الأدمن الرئيسي")
        conn.close()
        return redirect(url_for("staff"))
    conn.execute("DELETE FROM admin_users WHERE id = ?", (staff_id,))
    conn.commit()
    conn.close()
    flash("تم حذف الموظف")
    return redirect(url_for("staff"))


@app.route("/broadcast", methods=["GET", "POST"])
@permission_required("broadcast_send")
def broadcast():
    if request.method == "POST":
        import core
        message_text = request.form["message"].strip()
        target = request.form.get("target", "all")  # all / whatsapp / telegram

        def send_broadcast_job():
            conn2 = get_db()
            if target == "whatsapp":
                rows = conn2.execute("SELECT * FROM customers WHERE telegram_chat_id IS NULL").fetchall()
            elif target == "telegram":
                rows = conn2.execute("SELECT * FROM customers WHERE telegram_chat_id IS NOT NULL").fetchall()
            else:
                rows = conn2.execute("SELECT * FROM customers").fetchall()
            conn2.close()
            for c in rows:
                try:
                    core.send_message_to_customer(c, message_text)
                except Exception as e:
                    print(f"فشل إرسال رسالة جماعية للعميل {c['id']}:", e)

        threading.Thread(target=send_broadcast_job, daemon=True).start()
        flash("جاري إرسال الرسالة الجماعية دلوقتي في الخلفية، ممكن تاخد شوية وقت حسب عدد العملاء.")
        return redirect(url_for("broadcast"))

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) c FROM customers").fetchone()["c"]
    whatsapp_count = conn.execute("SELECT COUNT(*) c FROM customers WHERE telegram_chat_id IS NULL").fetchone()["c"]
    telegram_count = conn.execute("SELECT COUNT(*) c FROM customers WHERE telegram_chat_id IS NOT NULL").fetchone()["c"]
    conn.close()
    return render_template("broadcast.html", total=total, whatsapp_count=whatsapp_count, telegram_count=telegram_count)


if __name__ == "__main__":
    app.run(port=5001, debug=True)