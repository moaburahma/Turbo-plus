import sqlite3

conn = sqlite3.connect("database.db")

# البيانات التجريبية اللي هتتمسح بالكامل
for table in ["customers", "drivers", "orders", "complaints", "telegram_groups"]:
    conn.execute(f"DELETE FROM {table}")

# تصفير رصيد الأدمن
conn.execute("UPDATE admin_wallet SET balance = 0 WHERE id = 1")

conn.commit()
conn.close()
print("تم مسح كل بيانات التجربة بنجاح ✅")