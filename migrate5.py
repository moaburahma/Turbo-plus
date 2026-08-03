import sqlite3

conn = sqlite3.connect("database.db")
conn.execute("ALTER TABLE orders ADD COLUMN order_type TEXT")
conn.execute("ALTER TABLE orders ADD COLUMN vehicle_type TEXT")
conn.execute("ALTER TABLE customers ADD COLUMN draft_vehicle TEXT")
conn.execute("ALTER TABLE customers ADD COLUMN draft_pickup TEXT")
conn.execute("""
CREATE TABLE IF NOT EXISTS bot_messages (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

defaults = {
    "welcome_menu": "أهلاً بيك! اختار اللي يناسبك:",
    "button_order": "اطلب خدمة",
    "button_complaint": "تقدم بشكوى",
    "choose_service_type": "حدد نوع الخدمة المطلوبة:",
    "button_individual": "توصيل أفراد",
    "button_package": "توصيل طلبات",
    "ask_vehicle": "اختار نوع المركبة:",
    "button_car": "سيارة",
    "button_moto": "موتوسيكل",
    "ask_pickup": "اكتب مكان التحرك (من فين):",
    "ask_dropoff": "اكتب مكان التوصيل (لفين):",
    "ask_description": "تمام، اكتب وصف الخدمة المطلوبة بالتفصيل (هيجيب إيه من فين ويوديه فين):",
    "ask_price": "تمام، اكتب السعر اللي عايز تعرضه للتوصيل (بالجنيه، الحد الأدنى {min_price} جنيه):",
    "price_invalid": "من فضلك اكتب السعر رقم بس (مثال: 30)",
    "price_too_low": "السعر لازم يكون {min_price} جنيه على الأقل، اكتب سعر تاني:",
    "order_confirmed": "تم استلام طلبك بنجاح ✅\nكود الطلب: {order_code}\nالسعر: {price} جنيه\nهنبلغك أول ما مندوب يقبل الطلب.",
    "complaint_ask_order": "من فضلك اكتب كود الطلب اللي عندك مشكلة فيه:",
    "complaint_ask_message": "تمام، اكتب تفاصيل المشكلة اللي حصلتلك:",
    "complaint_confirmed": "تم استلام شكواك، هيتم التواصل معاك في أقرب وقت. 🙏",
    "driver_new_order": "طلب جديد #{order_code}:\n{details}\nالسعر المعروض: {price} جنيه",
    "button_accept": "قبول الطلب",
    "driver_order_taken": "للأسف الطلب ده اتاخد بالفعل من مندوب تاني.",
    "driver_low_balance": "رصيدك مش كافي لقبول طلبات جديدة. من فضلك اشحن رصيدك.",
    "driver_accept_confirmed": "تم قبول الطلب #{order_code} بنجاح.\nرقم العميل: {customer_phone}",
    "button_finish": "إنهاء الطلب",
    "customer_order_accepted": "تم قبول طلبك #{order_code} من مندوب، هيتم التواصل معاك قريبًا.",
    "driver_finish_confirmed": "تم إنهاء الطلب #{order_code}، تقدر تقبل طلبات جديدة دلوقتي.",
    "points_update": "🎉 اتضافلك {points_earned} نقطة! رصيدك الحالي من النقاط: {points_balance} نقطة.",
}
for k, v in defaults.items():
    conn.execute("INSERT OR IGNORE INTO bot_messages (key, value) VALUES (?, ?)", (k, v))

conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('individual_enabled', '0')")

conn.commit()
conn.close()
print("تم التحديث بنجاح ✅")