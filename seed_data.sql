-- بيانات حقيقية موجودة بالفعل في database.db، بننقلها لـ PostgreSQL

UPDATE admin_wallet SET balance = 0.0, updated_at = '2026-07-31 20:56:11' WHERE id = 1;

INSERT INTO admin_users (id, username, password_hash, permissions, is_main_admin, created_at) VALUES (1, 'admin', 'scrypt:32768:8:1$65AOb93Yx8GZrYjg$c2e34a9342aa1c0bdb1fce56a66500574bde3470e6b56a935e33eb7a29731c65d13723b7d36cc63effb8f660f854f9a2c4392c7af777c7c1ae0ed2b88ad73130', '{"orders": true, "drivers": true, "wallet": true, "settings": true, "complaints": true}', 1, '2026-08-01 07:00:11') ON CONFLICT (id) DO NOTHING;
SELECT setval('admin_users_id_seq', GREATEST((SELECT MAX(id) FROM admin_users), 1));

INSERT INTO settings (key, value) VALUES ('commission_percent', '10') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO settings (key, value) VALUES ('points_per_order', '1') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO settings (key, value) VALUES ('individual_enabled', '0') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO settings (key, value) VALUES ('telegram_drivers_group_id', '-5445890348') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

INSERT INTO bot_messages (key, value) VALUES ('welcome_menu', 'أهلاً بيك! اختار اللي يناسبك:') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_order', 'اطلب خدمة') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_complaint', 'تقدم بشكوى') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('choose_service_type', 'حدد نوع الخدمة المطلوبة:') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_individual', 'توصيل أفراد') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_package', 'توصيل طلبات') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('ask_vehicle', 'اختار نوع المركبة:') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_car', 'سيارة') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_moto', 'موتوسيكل') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('ask_pickup', 'اكتب مكان التحرك (من فين):') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('ask_dropoff', 'اكتب مكان التوصيل (لفين):') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('ask_description', 'تمام، اكتب وصف الخدمة المطلوبة بالتفصيل (هيجيب إيه من فين ويوديه فين):') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('ask_price', 'تمام، اكتب السعر اللي عايز تعرضه للتوصيل (بالجنيه، الحد الأدنى {min_price} جنيه):') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('price_invalid', 'من فضلك اكتب السعر رقم بس (مثال: 30)') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('price_too_low', 'السعر لازم يكون {min_price} جنيه على الأقل، اكتب سعر تاني:') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('order_confirmed', 'تم استلام طلبك بنجاح ✅
كود الطلب: {order_code}
السعر: {price} جنيه
هنبلغك أول ما مندوب يقبل الطلب.') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('complaint_ask_order', 'من فضلك اكتب كود الطلب اللي عندك مشكلة فيه:') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('complaint_ask_message', 'تمام، اكتب تفاصيل المشكلة اللي حصلتلك:') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('complaint_confirmed', 'تم استلام شكواك، هيتم التواصل معاك في أقرب وقت. 🙏') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('driver_new_order', 'طلب جديد #{order_code}:
{details}
السعر المعروض: {price} جنيه') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_accept', 'قبول الطلب') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('driver_order_taken', 'للأسف الطلب ده اتاخد بالفعل من مندوب تاني.') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('driver_low_balance', 'رصيدك مش كافي لقبول طلبات جديدة. من فضلك اشحن رصيدك.') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('driver_accept_confirmed', 'تم قبول الطلب #{order_code} بنجاح.
رقم العميل: {customer_phone}') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('button_finish', 'إنهاء الطلب') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('customer_order_accepted', 'تم قبول طلبك #{order_code} من مندوب، هيتم التواصل معاك قريبًا.') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('driver_finish_confirmed', 'تم إنهاء الطلب #{order_code}، تقدر تقبل طلبات جديدة دلوقتي.') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
INSERT INTO bot_messages (key, value) VALUES ('points_update', '🎉 اتضافلك {points_earned} نقطة! رصيدك الحالي من النقاط: {points_balance} نقطة.') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
