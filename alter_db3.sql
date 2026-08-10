-- 1) تقييم المندوب بعد كل طلب (من 1 لـ 5)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS rating INTEGER;

-- 2) جدول تتبع المكافآت اللي اتصرفت، عشان نظام المكافآت التلقائي متكررش الصرف في نفس الفترة
CREATE TABLE IF NOT EXISTS reward_grants (
    id SERIAL PRIMARY KEY,
    target TEXT NOT NULL,           -- 'customer' أو 'driver'
    target_id INTEGER NOT NULL,
    period TEXT NOT NULL,           -- 'daily' / 'weekly' / 'monthly'
    period_key TEXT NOT NULL,       -- مثلاً '2026-08-09' أو '2026-W32' أو '2026-08'
    granted_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE (target, target_id, period, period_key)
);

-- 3) إعدادات نظام المكافآت التلقائي (تُقرأ من لوحة الأدمن، كلها تقدري تغيّريها براحتك)
INSERT INTO settings (key, value) VALUES ('reward_customer_daily_threshold', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_customer_daily_points', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_customer_weekly_threshold', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_customer_weekly_points', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_customer_monthly_threshold', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_customer_monthly_points', '0') ON CONFLICT (key) DO NOTHING;

INSERT INTO settings (key, value) VALUES ('reward_driver_daily_threshold', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_driver_daily_amount', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_driver_weekly_threshold', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_driver_weekly_amount', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_driver_monthly_threshold', '0') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('reward_driver_monthly_amount', '0') ON CONFLICT (key) DO NOTHING;

-- 4) تقريب أي كسور موجودة حاليًا في الأرصدة لعلامتين عشريتين بس (تصليح المشكلة الحالية في رصيد الشركة)
UPDATE admin_wallet SET balance = ROUND(balance::numeric, 2);
UPDATE drivers SET balance = ROUND(balance::numeric, 2);
UPDATE customers SET points = ROUND(points::numeric, 2);