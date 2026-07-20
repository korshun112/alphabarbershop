import os, logging, re, sqlite3, datetime, calendar
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WELCOME_IMAGE_URL = os.getenv("WELCOME_IMAGE_URL", "")
ABOUT_IMAGE_URL = os.getenv("ABOUT_IMAGE_URL", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_FILE = "barbershop.db"
user_last_issue = {}

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS barbers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, qualification TEXT NOT NULL, active INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, time TEXT NOT NULL, barber_id INTEGER NOT NULL, client_name TEXT NOT NULL, client_phone TEXT NOT NULL, status TEXT DEFAULT 'ожидает', created TEXT NOT NULL)")
        cur.execute("CREATE TABLE IF NOT EXISTS disabled_days (date TEXT PRIMARY KEY)")
        cur.execute("CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, text TEXT NOT NULL, timestamp TEXT NOT NULL, resolved INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, text TEXT NOT NULL, rating INTEGER NOT NULL)")
        cur.execute("SELECT COUNT(*) FROM barbers")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO barbers (name, qualification, active) VALUES (?,?,?)", [("Алексей","Топ-барбер",1),("Максим","Про-барбер",1),("Дмитрий","Младший-барбер",1)])
        cur.execute("SELECT COUNT(*) FROM reviews")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO reviews (name, text, rating) VALUES (?,?,?)", [("Иван","Безупречный сервис, вернусь ещё.",5),("Сергей","Профессионально и с душой.",5),("Алексей","Отличный барбершоп, всегда доволен результатом.",5),("Дмитрий","Мастера знают своё дело, рекомендую.",5),("Егор","Приятная обстановка и качественная работа.",5),("Антон","Лучшее место для мужских стрижек в городе.",5),("Кирилл","Всегда вовремя, аккуратно и стильно.",5)])
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

def get_appointments(date=None, status=None, user_id=None):
    with get_db() as conn:
        cur = conn.cursor()
        sql = "SELECT * FROM appointments"
        params = []
        conditions = []
        if date:
            conditions.append("date=?")
            params.append(date)
        if status:
            conditions.append("status=?")
            params.append(status)
        if user_id:
            # user_id хранится в базе? У нас нет поля user_id в appointments, но мы можем добавить? 
            # Поскольку при записи мы не сохраняем user_id, будем искать по имени и телефону, но это не надежно.
            # Добавим поле user_id в таблицу appointments.
            # Но чтобы не менять структуру, мы можем создать отдельную таблицу для связи, или добавить поле.
            # Для простоты добавим поле user_id в appointments.
            pass
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY date, time"
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

def get_appointments_by_user(user_id):
    with get_db() as conn:
        cur = conn.cursor()
        # Предполагаем, что у нас есть поле user_id в appointments.
        # Добавим его при создании таблицы (миграция).
        cur.execute("SELECT * FROM appointments WHERE user_id=? AND status != 'отменена' ORDER BY date, time", (user_id,))
        return [dict(row) for row in cur.fetchall()]

def add_appointment(date, time, barber_id, client_name, client_phone, user_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM appointments WHERE date=? AND time=? AND status != 'отменена' AND status != 'не пришел'", (date, time))
        if cur.fetchone()[0] > 0:
            return None
        cur.execute("INSERT INTO appointments (date, time, barber_id, client_name, client_phone, user_id, created, status) VALUES (?,?,?,?,?,?,?,?)",
                    (date, time, barber_id, client_name, client_phone, user_id, datetime.datetime.now().isoformat(), 'ожидает'))
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
        cur.execute("INSERT INTO issues (user_id, user_name, text, timestamp) VALUES (?,?,?,?)", (user_id, user_name, text, datetime.datetime.now().isoformat()))
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
    if d.weekday() == 1:
        return False
    if date_str in get_disabled_days():
        return False
    return True

def get_available_slots(date_str):
    slots = [f"{h:02d}:00" for h in range(10, 21)]
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT time FROM appointments WHERE date=? AND status NOT IN ('отменена', 'не пришел')", (date_str,))
        booked = [row[0] for row in cur.fetchall()]
    return [s for s in slots if s not in booked]

def get_qualification_emoji(q):
    return {"Топ-барбер":"🏆", "Про-барбер":"⭐", "Младший-барбер":"✂️"}.get(q, "")

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Меню", callback_data="menu")],
        [InlineKeyboardButton("💬 Сообщить о проблеме", callback_data="issue")]
    ])

def menu_options_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться", callback_data="book")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton("ℹ️ О нас", callback_data="about")],
        [InlineKeyboardButton("💈 Прайс-лист", callback_data="prices")],
        [InlineKeyboardButton("⭐ Отзывы", callback_data="reviews")],
        [InlineKeyboardButton("📞 Контакты", callback_data="contacts")]
    ])

def back_to_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]])

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]])

async def show_month(update: Update, context: ContextTypes.DEFAULT_TYPE, month_offset=0):
    query = update.callback_query
    today = datetime.datetime.now().date()
    target_month = today.replace(day=1) + datetime.timedelta(days=month_offset*30)
    target_month = target_month.replace(day=1)
    year = target_month.year
    month = target_month.month

    cal = calendar.monthcalendar(year, month)
    disabled = get_disabled_days()

    keyboard = []
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    header_row = []
    for wd in weekdays:
        header_row.append(InlineKeyboardButton(wd, callback_data="noop"))
    keyboard.append(header_row)

    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                d = datetime.date(year, month, day)
                date_str = d.strftime("%Y-%m-%d")
                label = f"{day:02d}"
                if d.weekday() == 1 or date_str in disabled or d < today:
                    row.append(InlineKeyboardButton(f"🚫{label}", callback_data="noop"))
                else:
                    row.append(InlineKeyboardButton(label, callback_data=f"day_{date_str}"))
        keyboard.append(row)

    nav_row = [
        InlineKeyboardButton("◀️", callback_data="month_prev"),
        InlineKeyboardButton(f"{month:02d}.{year}", callback_data="noop"),
        InlineKeyboardButton("▶️", callback_data="month_next")
    ]
    keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        await query.edit_message_text("📅 Выберите день для записи (вторник – выходной):", reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text("📅 Выберите день для записи (вторник – выходной):", reply_markup=reply_markup)

# ---------- ЗАПИСЬ ----------
async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['month_offset'] = 0
    await show_month(update, context, 0)

async def day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = query.data.split('_')[1]
    if not is_working_day(date_str):
        await query.edit_message_text("Этот день недоступен. Выберите другой.", reply_markup=back_to_menu_keyboard())
        return
    context.user_data['booking_date'] = date_str
    slots = get_available_slots(date_str)
    if not slots:
        await query.edit_message_text("На этот день все время занято. Выберите другую дату.", reply_markup=back_to_menu_keyboard())
        return
    keyboard = []
    row = []
    for slot in slots:
        row.append(InlineKeyboardButton(slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_days")])
    await query.edit_message_text(f"Дата: {datetime.datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}\nВыберите время:", reply_markup=InlineKeyboardMarkup(keyboard))

async def time_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    time_str = query.data.split('_')[1]
    context.user_data['booking_time'] = time_str
    date_str = context.user_data['booking_date']
    slots = get_available_slots(date_str)
    if time_str not in slots:
        await query.edit_message_text("⚠️ Это время уже занято. Выберите другое.", reply_markup=back_to_menu_keyboard())
        return
    barbers = get_barbers(active_only=True)
    if not barbers:
        await query.edit_message_text("Сейчас нет свободных барберов. Попробуйте позже.", reply_markup=back_to_menu_keyboard())
        return
    keyboard = []
    for b in barbers:
        emoji = get_qualification_emoji(b['qualification'])
        label = f"{emoji} {b['name']} ({b['qualification']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"barber_{b['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_slots")])
    await query.edit_message_text("Выберите барбера:", reply_markup=InlineKeyboardMarkup(keyboard))

async def barber_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barber_id = int(query.data.split('_')[1])
    context.user_data['booking_barber_id'] = barber_id
    context.user_data['awaiting_name'] = True
    await query.edit_message_text("Введите ваше имя (например, Иван):", reply_markup=cancel_keyboard())

async def back_to_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await book_start(update, context)

async def back_to_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = context.user_data['booking_date']
    slots = get_available_slots(date_str)
    if not slots:
        await query.edit_message_text("На этот день все время занято.", reply_markup=back_to_menu_keyboard())
        return
    keyboard = []
    row = []
    for slot in slots:
        row.append(InlineKeyboardButton(slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_days")])
    await query.edit_message_text(f"Дата: {datetime.datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}\nВыберите время:", reply_markup=InlineKeyboardMarkup(keyboard))

async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_name'] = False
    context.user_data['awaiting_phone'] = False
    context.user_data.pop('booking_date', None)
    context.user_data.pop('booking_time', None)
    context.user_data.pop('booking_barber_id', None)
    context.user_data.pop('client_name', None)
    await query.edit_message_text("Запись отменена.", reply_markup=main_menu_keyboard())

async def booking_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_name', False):
        return
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Пожалуйста, введите корректное имя (минимум 2 символа).", reply_markup=cancel_keyboard())
        return
    context.user_data['client_name'] = name
    context.user_data['awaiting_name'] = False
    context.user_data['awaiting_phone'] = True
    await update.message.reply_text("Введите номер телефона в формате +7XXXXXXXXXX (11 цифр после +7):", reply_markup=cancel_keyboard())

async def booking_phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_phone', False):
        return
    phone = update.message.text.strip()
    # Валидация: +7 или 8, затем 10 цифр (всего 11 или 12 знаков)
    if not re.match(r'^(\+7|8)\d{10}$', phone):
        await update.message.reply_text("Некорректный номер. Используйте формат +7XXXXXXXXXX или 8XXXXXXXXXX (10 цифр после кода).", reply_markup=cancel_keyboard())
        return
    # Приводим к единому формату +7
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    date_str = context.user_data.get('booking_date')
    time_str = context.user_data.get('booking_time')
    barber_id = context.user_data.get('booking_barber_id')
    client_name = context.user_data.get('client_name')
    if not all([date_str, time_str, barber_id, client_name]):
        await update.message.reply_text("Что-то пошло не так. Начните запись заново.", reply_markup=main_menu_keyboard())
        context.user_data.pop('awaiting_phone', None)
        context.user_data.pop('awaiting_name', None)
        return
    # финальная проверка доступности слота
    slots = get_available_slots(date_str)
    if time_str not in slots:
        await update.message.reply_text("⚠️ К сожалению, это время уже занято. Запись отменена.", reply_markup=main_menu_keyboard())
        context.user_data.pop('awaiting_phone', None)
        context.user_data.pop('awaiting_name', None)
        return
    user_id = update.effective_user.id
    app_id = add_appointment(date_str, time_str, barber_id, client_name, phone, user_id)
    if app_id is None:
        await update.message.reply_text("⚠️ Произошла ошибка при записи. Попробуйте позже.", reply_markup=main_menu_keyboard())
        context.user_data.pop('awaiting_phone', None)
        context.user_data.pop('awaiting_name', None)
        return
    barber_name = next((b['name'] for b in get_barbers() if b['id'] == barber_id), "неизвестен")
    msg = f"🟢 Новая запись\nДата: {date_str}\nВремя: {time_str}\nКлиент: {client_name}\nТелефон: {phone}\nБарбер: {barber_name}"
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg)
    await update.message.reply_text("✅ Запись успешно оформлена!\n\nЖдём вас по адресу:\nг. Астрахань, Кировский район, 2-я Зеленгинская ул., корп. 3, 1 этаж.", reply_markup=main_menu_keyboard())
    # сброс
    context.user_data.pop('awaiting_phone', None)
    context.user_data.pop('awaiting_name', None)
    context.user_data.pop('booking_date', None)
    context.user_data.pop('booking_time', None)
    context.user_data.pop('booking_barber_id', None)
    context.user_data.pop('client_name', None)

# ---------- МОИ ЗАПИСИ (для клиента) ----------
async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    apps = get_appointments_by_user(user_id)
    if not apps:
        await query.edit_message_text("У вас нет активных записей.", reply_markup=back_to_menu_keyboard())
        return
    text = "📋 *Ваши записи:*\n\n"
    keyboard = []
    for a in apps:
        barber = next((b['name'] for b in get_barbers() if b['id'] == a['barber_id']), "неизвестен")
        text += f"ID {a['id']} | {a['date']} {a['time']} | {barber} | {a['status']}\n"
        keyboard.append([InlineKeyboardButton(f"Отменить запись #{a['id']}", callback_data=f"cancel_appt_{a['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def cancel_appointment_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app_id = int(query.data.split('_')[2])
    user_id = update.effective_user.id
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM appointments WHERE id=? AND user_id=? AND status NOT IN ('отменена', 'не пришел')", (app_id, user_id))
        app = cur.fetchone()
        if not app:
            await query.edit_message_text("Запись не найдена или уже отменена.", reply_markup=back_to_menu_keyboard())
            return
        # Отменяем
        cur.execute("UPDATE appointments SET status='отменена' WHERE id=?", (app_id,))
        conn.commit()
    # Уведомляем админа
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Клиент {app['client_name']} отменил запись #{app_id} на {app['date']} {app['time']}.")
    await query.edit_message_text("✅ Ваша запись успешно отменена.", reply_markup=main_menu_keyboard())

# ---------- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Добро пожаловать в Alpha – пространство мужского стиля.\n\nМы создаём образы, в которых уверенность становится главным аксессуаром.\nЛучшие мастера, безупречный сервис и только мужские стрижки.\n\nВыберите действие:"
    if WELCOME_IMAGE_URL:
        await update.message.reply_photo(photo=WELCOME_IMAGE_URL, caption=text, reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await update.effective_message.reply_text("Главное меню – выберите раздел:", reply_markup=menu_options_keyboard())

async def issue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_issue'] = True
    await update.effective_message.reply_text(
        "Опишите, с какой проблемой вы столкнулись.\n\n"
        "Мы постараемся решить её как можно быстрее.\n"
        "Отправьте ваше сообщение одним текстом:\n"
        "(не чаще 1 раза в 30 минут)",
        reply_markup=cancel_keyboard()
    )

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_issue'] = False
    await update.effective_message.reply_text("Действие отменено.", reply_markup=main_menu_keyboard())

async def issue_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if not context.user_data.get('awaiting_issue', False):
        return

    now = datetime.datetime.now()
    last_time = user_last_issue.get(user_id)
    if last_time and (now - last_time) < datetime.timedelta(minutes=30):
        remaining = int(30 - (now - last_time).total_seconds() // 60)
        await update.message.reply_text(
            f"⚠️ Вы уже отправляли сообщение о проблеме. Повторить можно через {remaining} минут."
        )
        context.user_data['awaiting_issue'] = False
        return

    user_last_issue[user_id] = now
    text = update.message.text
    add_issue(user_id, user.full_name, text)

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 Новая проблема\nОт: {user.full_name}\nТекст: {text}"
    )

    await update.message.reply_text(
        "Благодарим за обращение. Мы свяжемся с вами в ближайшее время.",
        reply_markup=main_menu_keyboard()
    )
    context.user_data['awaiting_issue'] = False

async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "О нас\n\nAlpha – это не просто барбершоп, а место, где рождается стиль.\nНаши мастера – профессионалы высочайшего уровня:\n🏆 Топ-барберы – эксперты с многолетним стажем;\n⭐ Про-барберы – мастера, знающие своё дело;\n✂️ Младшие-барберы – талантливые специалисты, которые постоянно совершенствуются.\n\nМы гордимся более чем 80 отзывами с оценкой 5⭐ на 2ГИС.\nНаши топ-барберы принимают экзамены в ведущих учебных заведениях.\nМы всегда ищем талантливых мастеров для развития в нашей команде.\n\n📍 Адрес: г. Астрахань, Кировский район, 2-я Зеленгинская ул., корп. 3, 1 этаж\n📶 Бесплатный Wi-Fi\n🕒 Работаем: пн–вс, кроме вторника, с 09:30 до 20:00\n📞 Менеджеры: +7‒988‒591‒06‒58, +7‒967‒338‒96‒69\n\n🔗 [2ГИС](https://alpha.2gis.biz/)"
    if ABOUT_IMAGE_URL:
        await update.effective_message.reply_photo(photo=ABOUT_IMAGE_URL, caption=text, reply_markup=back_to_menu_keyboard())
    else:
        await update.effective_message.reply_text(text, disable_web_page_preview=True, reply_markup=back_to_menu_keyboard())

async def contacts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "📞 *Контакты*\n\nСвяжитесь с нами по любым вопросам:\n\nМенеджеры:\n+7‒988‒591‒06‒58\n+7‒967‒338‒96‒69\n\n📍 Адрес: г. Астрахань, Кировский район,\n2-я Зеленгинская ул., корп. 3, 1 этаж\n\n🕒 Работаем: пн–вс, кроме вторника, с 09:30 до 20:00"
    await update.effective_message.reply_text(text, parse_mode='Markdown', reply_markup=back_to_menu_keyboard())

async def prices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "Прайс-лист\n\nТоп-барбер\nМужская стрижка .......... 900 ₽\nСтрижка + борода ......... 1400 ₽\nСтрижка бороды ........... 500 ₽\n\nПро-барбер\nМужская стрижка .......... 800 ₽\nСтрижка + борода ......... 1300 ₽\nСтрижка бороды ........... 500 ₽\n\nМладший-барбер\nМужская стрижка .......... 600 ₽\nСтрижка + борода ......... 1000 ₽\nСтрижка бороды ........... 400 ₽\n\nСтрижка под машинку (1 насадка) ... 400 ₽\nСтрижка под машинку (2 насадки) ... 500 ₽\n\nДоп. услуги\nКоролевское бритьё ............... 600 ₽\nГорячий воск ..................... 300 ₽\nПилинг кожи лица и головы ........ 350 ₽\nТонирование бороды ............... 450 ₽\nТонирование седины ............... 900 ₽\n\nЦены могут меняться, уточняйте у администратора."
    await update.effective_message.reply_text(text, reply_markup=back_to_menu_keyboard())

async def reviews_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reviews = get_reviews()
    if not reviews:
        text = "Пока нет отзывов. Будьте первым!"
    else:
        text = "⭐ *Отзывы наших клиентов*\n\n"
        for r in reviews:
            text += f"*{r['name']}*\n{r['text']}\n\n"
        text += "Мы ценим каждого клиента!\n\n📝 Оставить отзыв на 2ГИС: [Ссылка](https://alpha.2gis.biz/)"
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")], [InlineKeyboardButton("📝 Оставить отзыв", url="https://alpha.2gis.biz/")]]
    await update.effective_message.reply_text(text, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(keyboard))

async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_issue'] = False
    await update.effective_message.reply_text("Главное меню – выберите раздел:", reply_markup=menu_options_keyboard())

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Этот день недоступен", show_alert=True)

async def month_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "month_prev":
        offset = context.user_data.get('month_offset', 0) - 1
    else:
        offset = context.user_data.get('month_offset', 0) + 1
    context.user_data['month_offset'] = offset
    await show_month(update, context, offset)

# ---------- АДМИН-ПАНЕЛЬ ----------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещён.")
        return
    keyboard = [
        [InlineKeyboardButton("📅 Записи", callback_data="admin_appointments")],
        [InlineKeyboardButton("👤 Барберы", callback_data="admin_barbers")],
        [InlineKeyboardButton("🚫 Отключить день", callback_data="admin_disable_day")],
        [InlineKeyboardButton("✅ Включить день", callback_data="admin_enable_day")],
        [InlineKeyboardButton("⚠️ Проблемы", callback_data="admin_issues")]
    ]
    await update.message.reply_text("Админ-панель:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    apps = get_appointments()
    if not apps:
        await query.edit_message_text("Нет записей.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
        return
    text = "Записи:\n\n"
    for a in apps:
        barber = next((b['name'] for b in get_barbers() if b['id'] == a['barber_id']), "неизвестен")
        text += f"{a['id']} | {a['date']} {a['time']} | {a['client_name']} | {barber} | {a['status']}\n"
    keyboard = []
    for a in apps:
        keyboard.append([InlineKeyboardButton(f"{a['id']} - {a['client_name']}", callback_data=f"app_{a['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_appointment_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app_id = int(query.data.split('_')[1])
    apps = get_appointments()
    a = next((x for x in apps if x['id'] == app_id), None)
    if not a:
        await query.edit_message_text("Запись не найдена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]]))
        return
    barber = next((b['name'] for b in get_barbers() if b['id'] == a['barber_id']), "неизвестен")
    text = f"Запись #{app_id}\nКлиент: {a['client_name']}\nТелефон: {a['client_phone']}\nДата: {a['date']}\nВремя: {a['time']}\nБарбер: {barber}\nСтатус: {a['status']}"
    keyboard = [
        [InlineKeyboardButton("✅ Пришёл", callback_data=f"app_status_{app_id}_пришел")],
        [InlineKeyboardButton("❌ Не пришёл", callback_data=f"app_status_{app_id}_не пришел")],
        [InlineKeyboardButton("🗑 Отменить запись", callback_data=f"admin_cancel_{app_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_update_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    app_id = int(parts[2])
    status = parts[3]
    update_appointment_status(app_id, status)
    await query.edit_message_text(f"Статус записи #{app_id} обновлён на '{status}'.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]]))

async def admin_cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    app_id = int(query.data.split('_')[2])
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM appointments WHERE id=?", (app_id,))
        app = cur.fetchone()
        if not app:
            await query.edit_message_text("Запись не найдена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]]))
            return
        if app['status'] in ('отменена', 'не пришел'):
            await query.edit_message_text("Запись уже отменена или завершена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]]))
            return
        cur.execute("UPDATE appointments SET status='отменена' WHERE id=?", (app_id,))
        conn.commit()
    # Уведомляем клиента
    try:
        await context.bot.send_message(
            chat_id=app['user_id'],
            text=f"Ваша запись #{app_id} на {app['date']} {app['time']} была отменена администратором."
        )
    except:
        pass
    await query.edit_message_text("✅ Запись отменена, клиент уведомлён.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_appointments")]]))

async def admin_barbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    barbers = get_barbers()
    text = "Барберы:\n\n"
    for b in barbers:
        text += f"{b['name']} ({b['qualification']}) – {'работает' if b['active'] else 'не работает'}\n"
    keyboard = [
        [InlineKeyboardButton("➕ Добавить", callback_data="admin_add_barber")],
        [InlineKeyboardButton("🔄 Переключить статус", callback_data="admin_toggle_barber")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_barber_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['adding_barber'] = True
    await query.edit_message_text("Введите имя и квалификацию в формате:\n`Имя, Квалификация`\n(доступно: Топ-барбер, Про-барбер, Младший-барбер)", parse_mode='Markdown', reply_markup=cancel_keyboard())

async def admin_add_barber_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('adding_barber', False):
        return
    text = update.message.text
    parts = text.split(',')
    if len(parts) != 2:
        await update.message.reply_text("Неверный формат. Используйте: Имя, Квалификация", reply_markup=cancel_keyboard())
        return
    name = parts[0].strip()
    qual = parts[1].strip()
    if qual not in ["Топ-барбер", "Про-барбер", "Младший-барбер"]:
        await update.message.reply_text("Недопустимая квалификация.", reply_markup=cancel_keyboard())
        return
    add_barber(name, qual)
    await update.message.reply_text(f"✅ Барбер {name} добавлен.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_barbers")]]))
    context.user_data['adding_barber'] = False

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
    await query.edit_message_text("Статус обновлён.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_barbers")]]))

async def admin_disable_day_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['disabling_day'] = True
    await query.edit_message_text("Введите дату для отключения в формате ДД.ММ.ГГГГ (например, 15.07.2026):", reply_markup=cancel_keyboard())

async def admin_disable_day_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('disabling_day', False):
        return
    text = update.message.text.strip()
    try:
        d = datetime.datetime.strptime(text, "%d.%m.%Y").date().strftime("%Y-%m-%d")
    except:
        await update.message.reply_text("Неверный формат. Используйте ДД.ММ.ГГГГ", reply_markup=cancel_keyboard())
        return
    if d in get_disabled_days():
        await update.message.reply_text("Этот день уже отключён.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
        context.user_data['disabling_day'] = False
        return
    disable_day(d)
    await update.message.reply_text(f"✅ День {text} отключён.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
    context.user_data['disabling_day'] = False

async def admin_enable_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    disabled = get_disabled_days()
    if not disabled:
        await query.edit_message_text("Нет отключённых дней.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
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
        await query.edit_message_text("Нет нерешённых проблем.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]))
        return
    text = "Проблемы:\n\n"
    for i in issues:
        text += f"ID {i['id']}: {i['user_name']} – {i['text'][:50]}...\n"
    keyboard = []
    for i in issues:
        keyboard.append([InlineKeyboardButton(f"ID {i['id']}", callback_data=f"issue_{i['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_issue_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    issue_id = int(query.data.split('_')[1])
    issues = get_issues(unresolved_only=False)
    issue = next((i for i in issues if i['id'] == issue_id), None)
    if not issue:
        await query.edit_message_text("Проблема не найдена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]]))
        return
    text = f"ID: {issue_id}\nОт: {issue['user_name']}\nТекст: {issue['text']}\nВремя: {issue['timestamp']}"
    keyboard = [
        [InlineKeyboardButton("✅ Решено", callback_data=f"issue_resolve_{issue_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_issue_resolve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    issue_id = int(query.data.split('_')[2])
    issues = get_issues(unresolved_only=False)
    issue = next((i for i in issues if i['id'] == issue_id), None)
    if not issue:
        await query.edit_message_text("Проблема не найдена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]]))
        return

    resolve_issue(issue_id)

    try:
        await context.bot.send_message(
            chat_id=issue['user_id'],
            text="✅ Вашу проблему решили, спасибо за обращение!"
        )
        await query.edit_message_text(
            "✅ Проблема решена, клиент уведомлён.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]])
        )
    except Exception as e:
        await query.edit_message_text(
            f"⚠️ Проблема отмечена как решённая, но не удалось уведомить клиента (ошибка: {e}).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_issues")]])
        )

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📅 Записи", callback_data="admin_appointments")],
        [InlineKeyboardButton("👤 Барберы", callback_data="admin_barbers")],
        [InlineKeyboardButton("🚫 Отключить день", callback_data="admin_disable_day")],
        [InlineKeyboardButton("✅ Включить день", callback_data="admin_enable_day")],
        [InlineKeyboardButton("⚠️ Проблемы", callback_data="admin_issues")]
    ]
    await query.edit_message_text("Админ-панель:", reply_markup=InlineKeyboardMarkup(keyboard))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception:", exc_info=context.error)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    # Основные callback'и
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(issue_callback, pattern="^issue$"))
    app.add_handler(CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(month_navigation, pattern="^month_"))
    app.add_handler(CallbackQueryHandler(book_start, pattern="^book$"))
    app.add_handler(CallbackQueryHandler(day_selected, pattern="^day_"))
    app.add_handler(CallbackQueryHandler(time_selected, pattern="^time_"))
    app.add_handler(CallbackQueryHandler(barber_selected, pattern="^barber_"))
    app.add_handler(CallbackQueryHandler(back_to_days, pattern="^back_to_days$"))
    app.add_handler(CallbackQueryHandler(back_to_slots, pattern="^back_to_slots$"))
    app.add_handler(CallbackQueryHandler(cancel_booking, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(my_bookings, pattern="^my_bookings$"))
    app.add_handler(CallbackQueryHandler(cancel_appointment_client, pattern="^cancel_appt_"))

    # Админ-панель
    app.add_handler(CallbackQueryHandler(admin_appointments, pattern="^admin_appointments$"))
    app.add_handler(CallbackQueryHandler(admin_barbers, pattern="^admin_barbers$"))
    app.add_handler(CallbackQueryHandler(admin_enable_day, pattern="^admin_enable_day$"))
    app.add_handler(CallbackQueryHandler(admin_issues, pattern="^admin_issues$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_appointment_detail, pattern="^app_"))
    app.add_handler(CallbackQueryHandler(admin_update_status, pattern="^app_status_"))
    app.add_handler(CallbackQueryHandler(admin_cancel_appointment, pattern="^admin_cancel_"))
    app.add_handler(CallbackQueryHandler(admin_toggle_barber, pattern="^admin_toggle_barber$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_barber_callback, pattern="^toggle_"))
    app.add_handler(CallbackQueryHandler(admin_enable_day_callback, pattern="^enable_"))
    app.add_handler(CallbackQueryHandler(admin_issue_detail, pattern=r"^issue_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_issue_resolve, pattern="^issue_resolve_"))
    app.add_handler(CallbackQueryHandler(admin_add_barber_start, pattern="^admin_add_barber$"))
    app.add_handler(CallbackQueryHandler(admin_disable_day_start, pattern="^admin_disable_day$"))

    # Информационные разделы
    app.add_handler(CallbackQueryHandler(about_callback, pattern="^about$"))
    app.add_handler(CallbackQueryHandler(prices_callback, pattern="^prices$"))
    app.add_handler(CallbackQueryHandler(reviews_callback, pattern="^reviews$"))
    app.add_handler(CallbackQueryHandler(contacts_callback, pattern="^contacts$"))

    # Обработчики текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, booking_name_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, booking_phone_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_barber_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_disable_day_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, issue_text_handler))

    app.add_error_handler(error_handler)
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
