import sqlite3

conn = sqlite3.connect("database.db")
with open("schema.sql", "r", encoding="utf-8") as f:
    conn.executescript(f.read())

# قيم افتراضية أولية
conn.execute("INSERT OR IGNORE INTO admin_wallet (id, balance) VALUES (1, 0)")
conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('commission_percent', '10')")
conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('points_per_order', '1')")

conn.commit()
conn.close()
print("تم إنشاء قاعدة البيانات بنجاح ✅")