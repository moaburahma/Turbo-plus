CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    points INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    balance REAL DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    is_blocked INTEGER DEFAULT 0,
    monthly_orders_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code INTEGER UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL,
    driver_id INTEGER,
    status TEXT DEFAULT 'جديد',
    details TEXT,
    accepted_at TEXT,
    finished_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (driver_id) REFERENCES drivers(id)
);

CREATE TABLE IF NOT EXISTS admin_wallet (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    balance REAL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    driver_id INTEGER,
    message TEXT,
    status TEXT DEFAULT 'جديدة',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    permissions TEXT DEFAULT '{}',
    is_main_admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);