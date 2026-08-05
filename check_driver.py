import core

conn = core.get_db()
rows = conn.execute("SELECT id, phone, password_hash FROM drivers").fetchall()
for r in rows:
    print(dict(r))
conn.close()