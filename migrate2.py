import sqlite3

conn = sqlite3.connect("database.db")
conn.execute("ALTER TABLE drivers ADD COLUMN locked_until TEXT")
conn.commit()
conn.close()
print("تم التحديث بنجاح ✅")