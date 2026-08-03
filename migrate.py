import sqlite3

conn = sqlite3.connect("database.db")
conn.execute("ALTER TABLE customers ADD COLUMN state TEXT DEFAULT 'idle'")
conn.commit()
conn.close()
print("تم التحديث بنجاح ✅")