import sqlite3

conn = sqlite3.connect("database.db")
conn.row_factory = sqlite3.Row

conn.execute("""
CREATE TABLE IF NOT EXISTS telegram_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT UNIQUE NOT NULL,
    label TEXT,
    role TEXT DEFAULT 'drivers'
)
""")
conn.commit()

old = conn.execute("SELECT value FROM settings WHERE key='telegram_drivers_group_id'").fetchone()
if old and old["value"]:
    conn.execute("INSERT OR IGNORE INTO telegram_groups (chat_id, label, role) VALUES (?, ?, 'drivers')",
                 (old["value"], "جروب المناديب الأساسي"))
conn.commit()
conn.close()
print("تم التحديث بنجاح ✅")