import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("database.db")
username = "admin"
password = "admin123"  # غيّريها لباسورد قوي قبل التسليم للعميل
password_hash = generate_password_hash(password)
conn.execute(
    "INSERT OR IGNORE INTO admin_users (username, password_hash, permissions, is_main_admin) VALUES (?, ?, ?, ?)",
    (username, password_hash,
     '{"orders": true, "drivers": true, "wallet": true, "settings": true, "complaints": true}', 1)
)
conn.commit()
conn.close()
print("تم إنشاء حساب الأدمن ✅ (username: admin / password: admin123)")