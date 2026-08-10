-- شغّليها بعد alter_db.sql (أو بدل منه لو لسه محشغلتيهوش)
INSERT INTO settings (key, value) VALUES ('min_price_individual', '25') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('min_price_packages', '25') ON CONFLICT (key) DO NOTHING;
INSERT INTO settings (key, value) VALUES ('driver_accept_cooldown_minutes', '0') ON CONFLICT (key) DO NOTHING;