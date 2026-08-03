import sqlite3

conn = sqlite3.connect("database.db")
conn.execute("ALTER TABLE orders ADD COLUMN price REAL")
conn.execute("ALTER TABLE customers ADD COLUMN draft_details TEXT")
conn.commit()
conn.close()
print("تم التحديث بنجاح ✅")