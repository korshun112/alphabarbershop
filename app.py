import os, logging, re, sqlite3, datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_FILE = "barbershop.db"
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS barbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                qualification TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                barber_id INTEGER NOT NULL,
                client_name TEXT NOT NULL,
                client_phone TEXT NOT NULL,
                status TEXT DEFAULT 'ожидает',
                created TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS disabled_days (
                date TEXT PRIMARY KEY
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                resolved INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                text TEXT NOT NULL,
                rating INTEGER NOT NULL
            )
        """)
        cur.execute("SELECT COUNT(*) FROM barbers")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO barbers (name, qualification, active) VALUES (?,?,?)", [
                ("Алексей", "Топ-барбер", 1),
                ("Максим", "Про-барбер", 1),
                ("Дмитрий", "Младший-барбер", 1)
            ])
        cur.execute("SELECT COUNT(*) FROM reviews")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO reviews (name, text, rating) VALUES (?,?,?)", [
                ("Иван", "Лучшая стрижка в городе! Обязательно вернусь.", 5),
                ("Сергей", "Профессиональный подход и отличная атмосфера.", 5)
            ])
        conn.commit()
init_db()

def get_barbers(active_only=False):
    with get_db() as conn:
        cur = conn.cursor()
        if active_only:
            cur.execute("SELECT * FROM barbers WHERE active=1 ORDER BY id")
        else:
            cur.execute("SELECT * FROM barbers ORDER BY id")
        return [dict(row) for row in cur.fetchall()]

def get_appointments(date=None, status=None):
    with get_db() as conn:
        cur = conn.cursor()
        sql = "SELECT * FROM appointments"
        params = []
        if date:
            sql += " WHERE date=?"
            params.append(date)
        if status:
            sql += " AND status=? " if date else " WHERE status=?"
            params.append(status)
        sql += " ORDER BY date, time"
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

def get_disabled_days():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT date FROM disabled_days")
        return [row[0] for row in cur.fetchall()]

def get_issues(unresolved_only=True):
    with get_db() as conn:
        cur = conn.cursor()
        if unresolved_only:
            cur.execute("SELECT * FROM issues WHERE resolved=0 ORDER BY id")
        else:
            cur.execute("SELECT * FROM issues ORDER BY id")
        return [dict(row) for row in cur.fetchall()]

def get_reviews():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM reviews")
        return [dict(row) for row in cur.fetchall()]

def add_appointment(date, time, barber_id, client_name, client_phone):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO appointments (date, time, barber_id, client_name, client_phone, created) VALUES (?,?,?,?,?,?)",
            (date, time, barber_id, client_name, client_phone, datetime.datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid

def update_appointment_status(app_id, status):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE appointments SET status=? WHERE id=?", (status, app_id))
        conn.commit()

def add_issue(user_id, user_name, text):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO issues (user_id, user_name, text, timestamp) VALUES (?,?,?,?)",
                    (user_id, user_name, text, datetime.datetime.now().isoformat()))
        conn.commit()
        return cur.lastrowid

def resolve_issue(issue_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE issues SET resolved=1 WHERE id=?", (issue_id,))
        conn.commit()

def add_barber(name, qualification):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO barbers (name, qualification, active) VALUES (?,?,1)", (name, qualification))
        conn.commit()

def toggle_barber(barber_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE barbers SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?", (barber_id,))
        conn.commit()

def disable_day(date):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO disabled_days (date) VALUES (?)", (date,))
        conn.commit()

def enable_day(date):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM disabled_days WHERE date=?", (date,))
        conn.commit()

def is_working_day(date_str):
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    if d.weekday() == 1:  # вторник
        return False
    if date_str in get_disabled_days():
        return False
    return True

def get_available_slots(date_str):
    slots = [f"{h:02d}:00" for h in range(10, 22)]  # 10:00 - 21:00
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT time FROM appointments WHERE date=? AND status != 'не пришел'", (date_str,))
        booked = [row[0] for row in cur.fetchall()]
    return [s for s in slots if s not in booked]

def get_qualification_emoji(q):
    return {"Топ-барбер":"🏆", "Про-барбер":"⭐", "Младший-барбер":"✂️"}.get(q, "")

DAY, TIME_SLOT, BARBER, CLIENT_NAME, CLIENT_PHONE = range(5)
ADD_BARBER_STATE, DISABLE_DAY_STATE = range(6, 8)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️\n"
        "🟢 *ДОБРО ПОЖАЛОВАТЬ В ALPHA* 🟢\n"
        "🟡 *МУЖСКАЯ СТРИЖКА С ХАРАКТЕРОМ*\n"
        "⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️\n\n"
        "Мы создаём стиль, который подчёркивает вашу индивидуальность.\n"
        "Лучшие мастера, премиальная атмосфера и только мужские стрижки.\n\n"
        "Выберите действие:\n"
        "─────────────────────\n"
        "📋 *Меню* – запись, цены, о нас, отзывы\n"
        "⚠️ *Сообщить о проблеме* – сообщить о баге или ошибке"
    )
    keyboard = [[KeyboardButton("📋 Меню"), KeyboardButton("⚠️ Сообщить о проблеме")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Записаться на стрижку", callback_data="book")],
        [InlineKeyboardButton("ℹ️ О нас", callback_data="about")],
        [InlineKeyboardButton("💈 Прайс-лист", callback_data="prices")],
        [InlineKeyboardButton("🌟 Отзывы", callback_data="reviews")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚫️ *ГЛАВНОЕ МЕНЮ* ⚫️\n\nВыберите интересующий раздел:", parse_mode='Markdown', reply_markup=reply_markup)

async def issue_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ *Сообщить о проблеме*\n\n"
        "Опишите, с какой проблемой вы столкнулись при работе с ботом.\n"
        "Мы постараемся решить её как можно быстрее.\n\n"
        "Напишите ваше сообщение одним сообщением:"
    )
    return "ISSUE"

async def handle_issue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    issue_id = add_issue(user.id, user.full_name, text)
    for admin_id in ADMIN_IDS:
        await context.bot.send_message(chat_id=admin_id, text=f"🆕 *Новая проблема*\nОт: {user.full_name}\nТекст: {text}")
    await update.message.reply_text("✅ Сообщение отправлено. Мы скоро его обработаем.")
    return ConversationHandler.END

async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "ℹ️ *О BARBERSHOP ALPHA*\n\n"
        "⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️\n"
        "🟢 *Мужской стиль – наша философия*\n\n"
        "Мы – премиальный барбершоп, где каждый клиент получает\n"
        "индивидуальный подход и безупречный результат.\n\n"
        "👔 *Наши мастера:*\n"
        "🏆 *Топ-барберы* – эксперты с многолетним стажем, наставники\n"
        "⭐ *Про-барберы* – профи высокого уровня\n"
        "✂️ *Младшие-барберы* – талантливые специалисты, постоянно растущие\n\n"
        "🏅 *Достижения:*\n"
        "• Более 80 оценок 5⭐ на 2ГИС\n"
        "• Наши топ-барберы принимают экзамены в университетах и колледжах\n"
        "• Мы ищем талантливых мастеров для развития в нашей команде\n\n"
        "📍 *Адрес:* г. Астрахань, Кировский район,\n"
        "2-я Зеленгинская улица, корпус 3, 1 этаж\n"
        "📶 Бесплатный Wi-Fi\n\n"
        "🟡 *Работаем:* Пн–Вс, кроме вторника, с 10:00 до 21:00\n"
        "─────────────────────\n"
        "🔗 [Ссылка на 2ГИС](https://alpha.2gis.biz/)\n\n"
        "Запись через бот или по телефону +7 (999) 123-45-67"
    )
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
    await query.edit_message_text(text, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard))

async def prices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "💈 *ПРАЙС-ЛИСТ*\n"
        "⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️⚫️\n\n"
        "*ТОП-БАРБЕР*\n"
        "Мужская стрижка .......... 900 ₽\n"
        "Стрижка + борода ......... 1400 ₽\n"
        "Стрижка бороды ........... 500 ₽\n\n"
        "*ПРО-БАРБЕР*\n"
        "Мужская стрижка .......... 800 ₽\n"
        "Стрижка + борода ......... 1300 ₽\n"
        "Стрижка бороды ........... 500 ₽\n\n"
        "*МЛАДШИЙ-БАРБЕР*\n"
        "Мужская стрижка .......... 600 ₽\n"
        "Стрижка + борода ......... 1000 ₽\n"
        "Стрижка бороды ........... 400 ₽\n\n"
        "*ДОП. УСЛУГИ*\n"
        "Стрижка под машинку (1 насадка) ... 400 ₽\n"
        "Стрижка под машинку (2 насадки) ... 500 ₽\n"
        "Королевское спитье ............... 600 ₽\n\n"
        "Цены могут меняться, уточняйте у администратора."
    )
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def reviews_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reviews = get_reviews()
    text = "🌟 *ОТЗЫВЫ*\n\n"
    for r in reviews:
        text += f"⭐ {r['name']}: {r['text']}\n\n"
    text += "Мы ценим каждого клиента и стремимся к совершенству!"
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # формируем доступные дни на 14 дней
    start_dt = datetime.datetime.now().date()
    days = [start_dt + datetime.timedelta(days=i) for i in range(14)]
    available = [d for d in days if is_working_day(d.strftime("%Y-%m-%d"))]
    if not available:
        await query.edit_message_text("😔 В ближайшее время нет свободных дней для записи.")
        return ConversationHandler.END
    keyboard = []
    row = []
    for d in available[:7]:
        label = d.strftime("%d.%m")
        data = d.strftime("%Y-%m-%d")
        row.append(InlineKeyboardButton(label, callback_data=f"day_{data}"))
        if len(row) == 4:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    await query.edit_message_text("📅 *Выберите день:*", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return DAY

async def day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = query.data.split('_')[1]
    if not is_working_day(date_str):
        await query.edit_message_text("Извините, этот день недоступен для записи. Выберите другой.")
        return DAY
    context.user_data['date'] = date_str
    slots = get_available_slots(date_str)
    if not slots:
        await query.edit_message_text("😔 На этот день все время уже занято. Выберите другую дату.")
        return DAY
    keyboard = []
    row = []
    for slot in slots:
        row.append(InlineKeyboardButton(slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_days")])
    await query.edit_message_text(f"📅 *{datetime.datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}*\nВыберите удобное время:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return TIME_SLOT

async def time_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    time_str = query.data.split('_')[1]
    context.user_data['time'] = time_str
    barbers = get_barbers(active_only=True)
    if not barbers:
        await query.edit_message_text("😔 На данный момент нет свободных барберов. Попробуйте позже.")
        return TIME_SLOT
    keyboard = []
    for b in barbers:
        emoji = get_qualification_emoji(b['qualification'])
        label = f"{emoji} {b['name']} ({b['qualification']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"barber_{b['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_slots")])
    await query.edit_message_text("👤 *Выберите барбера:*", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return BARBER

async def barber_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barber_id = int(query.data.split('_')[1])
    context.user_data['barber_id'] = barber_id
    await query.edit_message_text("✍️ *Введите ваше имя:*\n(например, Иван)", parse_mode='Markdown')
    return CLIENT_NAME

async def client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Пожалуйста, введите корректное имя (минимум 2 символа).")
        return CLIENT_NAME
    context.user_data['name'] = name
    await update.message.reply_text("📞 *Введите ваш номер телефона:*\n(в формате +79991234567)", parse_mode='Markdown')
    return CLIENT_PHONE

async def client_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not re.match(r'^\+?\d{10,15}$', phone):
        await update.message.reply_text("Некорректный номер. Попробуйте снова (только цифры и +).")
        return CLIENT_PHONE
    date_str = context.user_data['date']
    time_str = context.user_data['time']
    barber_id = context.user_data['barber_id']
    client_name = context.user_data['name']
    app_id = add_appointment(date_str, time_str, barber_id, client_name, phone)
    barber_name = next((b['name'] for b in get_barbers() if b['id'] == barber_id), "неизвестен")
    msg = (f"🟢 *НОВАЯ ЗАПИСЬ*\nДата: {date_str}\nВремя: {time_str}\nКлиент: {client_name}\nТелефон: {phone}\nБарбер: {barber_name}\nСтатус: ожидает")
    for admin_id in ADMIN_IDS:
        await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode='Markdown')
    await update.message.reply_text(
        "✅ *Запись успешно оформлена!*\n\nМы ждём вас в указанное время.\nАдрес: г. Астрахань, Кировский район, 2-я Зеленгинская ул., корп. 3, 1 этаж.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def back_to_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await book_start(update, context)

async def back_to_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = context.user_data['date']
    slots = get_available_slots(date_str)
    if not slots:
        await query.edit_message_text("😔 На этот день все время уже занято. Выберите другую дату.")
        return DAY
    keyboard = []
    row = []
    for slot in slots:
        row.append(InlineKeyboardButton(slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_days")])
    await query.edit_message_text(f"📅 *{datetime.datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}*\nВыберите удобное время:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return TIME_SLOT

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет доступа к админ-панели.")
        return
    keyboard = [
        [InlineKeyboardButton("📅 Записи", callback_data="admin_appointments")],
        [InlineKeyboardButton("👤 Барберы", callback_data="admin_barbers")],
        [InlineKeyboardButton("🚫 Отключить день", callback_data="admin_disable_day")],
        [InlineKeyboardButton("✅ Включить день", callback_data="admin_enable_day")],
        [InlineKeyboardButton("⚠️ Проблемы", callback_data="admin_issues")]
    ]
    await update.message.reply_text("🔧 *АДМИН-ПАНЕЛЬ*\n\nВыберите действие:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    apps = get_appointments()
    if not apps:
        await query.edit_message_text("📭 Нет записей.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
        return
    text = "📋 *Записи*\n\n"
    for a in apps:
        barber = next((b['name'] for b in get_barbers() if b['id'] == a['barber_id']), "неизвестен")
        text += f"ID {a['id']} | {a['date']} {a['time']} | {a['client_name']} | {barber} | {a['status']}\n"
    keyboard = []
    for a in apps:
        keyboard.append([InlineKeyboardButton(f"{a['id']} - {a['client_name']}", callback_data=f"app_{a['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_appointment_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app_id = int(query.data.split('_')[1])
    apps = get_appointments()
    a = next((x for x in apps if x['id'] == app_id), None)
    if not a:
        await query.edit_message_text("Запись не найдена.")
        return
    barber = next((b['name'] for b in get_barbers() if b['id'] == a['barber_id']), "неизвестен")
    text = (f"📌 *Запись #{app_id}*\nКлиент: {a['client_name']}\nТелефон: {a['client_phone']}\nДата: {a['date']}\nВремя: {a['time']}\nБарбер: {barber}\nСтатус: {a['status']}")
    keyboard = [
        [InlineKeyboardButton("✅ Пришёл", callback_data=f"app_status_{app_id}_пришел")],
        [InlineKeyboardButton("❌ Не пришёл", callback_data=f"app_status_{app_id}_не пришел")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]
    ]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_update_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    app_id = int(parts[2])
    status = parts[3]
    update_appointment_status(app_id, status)
    await query.edit_message_text(f"Статус записи #{app_id} обновлён на '{status}'.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]]))

async def admin_barbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barbers = get_barbers()
    text = "👤 *Барберы*\n\n"
    for b in barbers:
        text += f"{b['name']} ({b['qualification']}) – {'🟢 работает' if b['active'] else '🔴 не работает'}\n"
    keyboard = [
        [InlineKeyboardButton("➕ Добавить барбера", callback_data="admin_add_barber")],
        [InlineKeyboardButton("🔄 Переключить статус", callback_data="admin_toggle_barber")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
    ]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_barber_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите имя и квалификацию нового барбера в формате:\n`Имя, Квалификация`\n(Квалификация: Топ-барбер, Про-барбер, Младший-барбер)", parse_mode='Markdown')
    return ADD_BARBER_STATE

async def admin_add_barber_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parts = text.split(',')
    if len(parts) != 2:
        await update.message.reply_text("Неверный формат. Используйте: Имя, Квалификация")
        return ADD_BARBER_STATE
    name = parts[0].strip()
    qual = parts[1].strip()
    if qual not in ["Топ-барбер", "Про-барбер", "Младший-барбер"]:
        await update.message.reply_text("Недопустимая квалификация. Доступны: Топ-барбер, Про-барбер, Младший-барбер")
        return ADD_BARBER_STATE
    add_barber(name, qual)
    await update.message.reply_text(f"✅ Барбер {name} добавлен.")
    return ConversationHandler.END

async def admin_toggle_barber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barbers = get_barbers()
    keyboard = []
    for b in barbers:
        status = "🟢" if b['active'] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {b['name']}", callback_data=f"toggle_{b['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_barbers")])
    await query.edit_message_text("Выберите барбера для смены статуса:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_toggle_barber_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barber_id = int(query.data.split('_')[1])
    toggle_barber(barber_id)
    await query.edit_message_text("Статус барбера обновлён.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_barbers")]]))

async def admin_disable_day_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите дату для отключения в формате ДД.ММ.ГГГГ (например, 15.07.2026):")
    return DISABLE_DAY_STATE

async def admin_disable_day_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        d = datetime.datetime.strptime(text, "%d.%m.%Y").date().strftime("%Y-%m-%d")
    except:
        await update.message.reply_text("Неверный формат. Используйте ДД.ММ.ГГГГ")
        return DISABLE_DAY_STATE
    if d in get_disabled_days():
        await update.message.reply_text("Этот день уже отключён.")
        return ConversationHandler.END
    disable_day(d)
    await update.message.reply_text(f"✅ День {text} отключён для записи.")
    return ConversationHandler.END

async def admin_enable_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disabled = get_disabled_days()
    if not disabled:
        await query.edit_message_text("Нет отключённых дней.")
        return
    keyboard = []
    for day in disabled:
        keyboard.append([InlineKeyboardButton(day, callback_data=f"enable_{day}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text("Выберите день для включения:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_enable_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day_str = query.data.split('_')[1]
    enable_day(day_str)
    await query.edit_message_text(f"✅ День {day_str} включён.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))

async def admin_issues(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    issues = get_issues(unresolved_only=True)
    if not issues:
        await query.edit_message_text("✅ Нет нерешённых проблем.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
        return
    text = "⚠️ *Проблемы*\n\n"
    for i in issues:
        text += f"ID {i['id']}: {i['user_name']} – {i['text'][:50]}...\n"
    keyboard = []
    for i in issues:
        keyboard.append([InlineKeyboardButton(f"ID {i['id']}", callback_data=f"issue_{i['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_issue_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    issue_id = int(query.data.split('_')[1])
    issues = get_issues(unresolved_only=False)
    issue = next((i for i in issues if i['id'] == issue_id), None)
    if not issue:
        await query.edit_message_text("Проблема не найдена.")
        return
    text = f"ID: {issue_id}\nОт: {issue['user_name']}\nТекст: {issue['text']}\nВремя: {issue['timestamp']}"
    keyboard = [
        [InlineKeyboardButton("✅ Решено", callback_data=f"issue_resolve_{issue_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]
    ]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_issue_resolve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    issue_id = int(query.data.split('_')[2])
    resolve_issue(issue_id)
    await query.edit_message_text("Проблема отмечена как решённая.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]]))

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await admin(update, context)  

async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Возврат в главное меню...")
    keyboard = [
        [InlineKeyboardButton("📅 Записаться", callback_data="book")],
        [InlineKeyboardButton("ℹ️ О нас", callback_data="about")],
        [InlineKeyboardButton("💈 Прайс-лист", callback_data="prices")],
        [InlineKeyboardButton("🌟 Отзывы", callback_data="reviews")]
    ]
    await update.effective_message.reply_text("⚫️ *ГЛАВНОЕ МЕНЮ* ⚫️\n\nВыберите раздел:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(MessageHandler(filters.Regex("^📋 Меню$"), menu_button))
    app.add_handler(MessageHandler(filters.Regex("^⚠️ Сообщить о проблеме$"), issue_button))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_issue))

    book_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(book_start, pattern="^book$")],
        states={
            DAY: [CallbackQueryHandler(day_selected, pattern="^day_")],
            TIME_SLOT: [CallbackQueryHandler(time_selected, pattern="^time_")],
            BARBER: [CallbackQueryHandler(barber_selected, pattern="^barber_")],
            CLIENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_name)],
            CLIENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_phone)],
        },
        fallbacks=[CallbackQueryHandler(back_to_days, pattern="^back_to_days$"),
                   CallbackQueryHandler(back_to_slots, pattern="^back_to_slots$"),
                   CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$")],
        per_message=True,
    )
    app.add_handler(book_conv)

    add_barber_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_barber_start, pattern="^admin_add_barber$")],
        states={ADD_BARBER_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_barber_text)]},
        fallbacks=[CommandHandler("admin", admin)],
        per_message=True,
    )
    app.add_handler(add_barber_conv)

    disable_day_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_disable_day_start, pattern="^admin_disable_day$")],
        states={DISABLE_DAY_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_disable_day_text)]},
        fallbacks=[CommandHandler("admin", admin)],
        per_message=True,
    )
    app.add_handler(disable_day_conv)

    admin_patterns = [
        "admin_appointments", "admin_barbers", "admin_enable_day", "admin_issues",
        "admin_back", "app_", "app_status_", "admin_toggle_barber", "toggle_",
        "enable_", "issue_", "issue_resolve_"
    ]
    app.add_handler(CallbackQueryHandler(admin_appointments, pattern="^admin_appointments$"))
    app.add_handler(CallbackQueryHandler(admin_barbers, pattern="^admin_barbers$"))
    app.add_handler(CallbackQueryHandler(admin_enable_day, pattern="^admin_enable_day$"))
    app.add_handler(CallbackQueryHandler(admin_issues, pattern="^admin_issues$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_appointment_detail, pattern="^app_"))
    app.add_handler(CallbackQueryHandler(admin_update_status, pattern="^app_status_"))
    app.add_handler(CallbackQueryHandler(admin_toggle_barber, pattern="^admin_toggle_barber$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_barber_callback, pattern="^toggle_"))
    app.add_handler(CallbackQueryHandler(admin_enable_day_callback, pattern="^enable_"))
    app.add_handler(CallbackQueryHandler(admin_issue_detail, pattern="^issue_"))
    app.add_handler(CallbackQueryHandler(admin_issue_resolve, pattern="^issue_resolve_"))

    app.add_handler(CallbackQueryHandler(about_callback, pattern="^about$"))
    app.add_handler(CallbackQueryHandler(prices_callback, pattern="^prices$"))
    app.add_handler(CallbackQueryHandler(reviews_callback, pattern="^reviews$"))

    app.add_handler(CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$"))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
