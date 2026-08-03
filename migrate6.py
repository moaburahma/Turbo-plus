import sqlite3

conn = sqlite3.connect("database.db")
conn.execute("ALTER TABLE customers ADD COLUMN telegram_chat_id TEXT")
conn.execute("ALTER TABLE drivers ADD COLUMN telegram_user_id TEXT")
conn.execute("ALTER TABLE orders ADD COLUMN source TEXT DEFAULT 'whatsapp'")
conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_drivers_group_id', '')")
conn.commit()
conn.close()
print("تم التحديث بنجاح ✅")