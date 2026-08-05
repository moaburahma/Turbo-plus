from werkzeug.security import generate_password_hash
import core

conn = core.get_db()
conn.execute(
    "INSERT INTO drivers (phone, name, balance, is_active, is_blocked, monthly_orders_count, password_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ("201107811694", "مندوب تجريبي", 50, 1, 0, 0, generate_password_hash("driver123"))
)
conn.commit()
conn.close()
print("تم إضافة المندوب بنجاح ✅ (تسجيل الدخول: 201107811694 / driver123)")