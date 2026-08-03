import sqlite3

conn = sqlite3.connect("database.db")
conn.execute("UPDATE settings SET value = ? WHERE key = 'telegram_drivers_group_id'", ("-5445890348",))
conn.commit()
conn.close()
print("تم الحفظ بنجاح ✅")