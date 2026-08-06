from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from whatsapp_webhook import whatsapp_bp

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key-later")
app.register_blueprint(whatsapp_bp)


DATABASE_URL = os.getenv("DATABASE_URL")


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
@login_required
def orders():
    search = request.args.get("q", "")
    conn = get_db()
    query = """SELECT orders.*, customers.phone as customer_phone
               FROM orders LEFT JOIN customers ON orders.customer_id = customers.id"""
    if search:
        rows = conn.execute(query + " WHERE CAST(orders.order_code AS TEXT) LIKE ? ORDER BY orders.id DESC",
                             (f"%{search}%",)).fetchall()
    else:
        rows = conn.execute(query + " ORDER BY orders.id DESC").fetchall()
    conn.close()
    return render_template("orders.html", orders=rows, search=search)


@app.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
def update_order_status(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (request.form["status"], order_id))
    conn.commit()
    conn.close()
    return redirect(url_for("orders"))


# ============ إدارة المناديب ============
@app.route("/drivers")
@login_required
def drivers():
    conn = get_db()
    rows = conn.execute("SELECT * FROM drivers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("drivers.html", drivers=rows)


@app.route("/drivers/add", methods=["POST"])
@login_required
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
    conn = get_db()
    if action == "block":
        conn.execute("UPDATE drivers SET is_blocked = 1 WHERE id = ?", (driver_id,))
    elif action == "unblock":
        conn.execute("UPDATE drivers SET is_blocked = 0 WHERE id = ?", (driver_id,))
    elif action == "add_balance":
        conn.execute("UPDATE drivers SET balance = balance + ? WHERE id = ?", (float(request.form["amount"]), driver_id))
    conn.commit()
    conn.close()
    return redirect(url_for("drivers"))


# ============ الإعدادات ============
@app.route("/drivers/<int:driver_id>/delete", methods=["POST"])
@login_required
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
@login_required
def update_driver_telegram_id(driver_id):
    conn = get_db()
    conn.execute("UPDATE drivers SET telegram_user_id = ? WHERE id = ?",
                 (request.form["telegram_user_id"] or None, driver_id))
    conn.commit()
    conn.close()
    flash("تم تحديث Telegram ID للمندوب")
    return redirect(url_for("drivers"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    conn = get_db()
    if request.method == "POST":
        if "commission_percent" in request.form:
            conn.execute("UPDATE settings SET value = ? WHERE key = 'commission_percent'", (request.form["commission_percent"],))
            conn.execute("UPDATE settings SET value = ? WHERE key = 'points_per_order'", (request.form["points_per_order"],))
            individual = "1" if request.form.get("individual_enabled") == "on" else "0"
            conn.execute("UPDATE settings SET value = ? WHERE key = 'individual_enabled'", (individual,))
            conn.commit()
            flash("تم حفظ الإعدادات")

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

    commission = conn.execute("SELECT value FROM settings WHERE key='commission_percent'").fetchone()["value"]
    points = conn.execute("SELECT value FROM settings WHERE key='points_per_order'").fetchone()["value"]
    individual_enabled = conn.execute("SELECT value FROM settings WHERE key='individual_enabled'").fetchone()["value"]
    conn.close()
    return render_template("settings.html", commission=commission, points=points, individual_enabled=individual_enabled)

# ============ نصوص البوت ============
@app.route("/messages")
@login_required
def messages():
    conn = get_db()
    rows = conn.execute("SELECT * FROM bot_messages ORDER BY key").fetchall()
    conn.close()
    return render_template("messages.html", messages=rows)


@app.route("/messages/update", methods=["POST"])
@login_required
def update_messages():
    conn = get_db()
    for key in request.form:
        conn.execute("UPDATE bot_messages SET value = ? WHERE key = ?", (request.form[key], key))
    conn.commit()
    conn.close()
    return redirect(url_for("messages"))


# ============ الشكاوى ============
@app.route("/complaints")
@login_required
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
    conn.close()
    return render_template("driver_dashboard.html", driver=driver, orders=my_orders)


@app.route("/available-orders")
@driver_login_required
def available_orders():
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
    ok, msg, order, extra = core.finish_order(session["driver_id"], order_code)
    flash(msg if not ok else f"تم إنهاء الطلب #{order_code}")
    return redirect(url_for("driver_dashboard"))

@app.route("/complaints/<int:complaint_id>/reply", methods=["POST"])
@login_required
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
@login_required
def telegram_groups():
    conn = get_db()
    rows = conn.execute("SELECT * FROM telegram_groups").fetchall()
    conn.close()
    return render_template("telegram_groups.html", groups=rows)


@app.route("/telegram-groups/add", methods=["POST"])
@login_required
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
@login_required
def delete_telegram_group(group_id):
    conn = get_db()
    conn.execute("DELETE FROM telegram_groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("telegram_groups"))

@app.route("/customers")
@login_required
def customers():
    conn = get_db()
    rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("customers.html", customers=rows)


@app.route("/customers/<int:customer_id>/add_points", methods=["POST"])
@login_required
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
@login_required
def set_driver_password(driver_id):
    conn = get_db()
    conn.execute("UPDATE drivers SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(request.form["new_password"]), driver_id))
    conn.commit()
    conn.close()
    flash("تم تحديث كلمة مرور المندوب")
    return redirect(url_for("drivers"))


if __name__ == "__main__":
    app.run(port=5001, debug=True)