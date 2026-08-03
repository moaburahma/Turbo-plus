-- ============================================================
-- سكريبت إنشاء الجداول على PostgreSQL
-- مبني على البنية الحقيقية المستخرجة من database.db (SQLite)
-- ============================================================

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    points DOUBLE PRECISION DEFAULT 0,
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
    state TEXT DEFAULT 'idle',
    draft_details TEXT,
    draft_vehicle TEXT,
    draft_pickup TEXT,
    telegram_chat_id TEXT
);

CREATE TABLE IF NOT EXISTS drivers (
    id SERIAL PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    balance DOUBLE PRECISION DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    is_blocked INTEGER DEFAULT 0,
    monthly_orders_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
    locked_until TEXT,
    password_hash TEXT,
    telegram_user_id TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    order_code INTEGER UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    driver_id INTEGER REFERENCES drivers(id),
    status TEXT DEFAULT 'جديد',
    details TEXT,
    accepted_at TEXT,
    finished_at TEXT,
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
    price DOUBLE PRECISION,
    order_type TEXT,
    vehicle_type TEXT,
    source TEXT DEFAULT 'whatsapp'
);

CREATE TABLE IF NOT EXISTS admin_wallet (
    id SERIAL PRIMARY KEY,
    balance DOUBLE PRECISION DEFAULT 0,
    updated_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS complaints (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    customer_id INTEGER NOT NULL,
    driver_id INTEGER,
    message TEXT,
    status TEXT DEFAULT 'جديدة',
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    permissions TEXT DEFAULT '{}',
    is_main_admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS bot_messages (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS telegram_groups (
    id SERIAL PRIMARY KEY,
    chat_id TEXT UNIQUE NOT NULL,
    label TEXT,
    role TEXT DEFAULT 'drivers'
);

-- تأكد إن صف admin_wallet الأساسي (id=1) موجود دايمًا
INSERT INTO admin_wallet (id, balance) VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- إعادة ضبط الـ sequence بتاعة admin_wallet عشان تبدأ من بعد id=1
SELECT setval('admin_wallet_id_seq', GREATEST((SELECT MAX(id) FROM admin_wallet), 1));
