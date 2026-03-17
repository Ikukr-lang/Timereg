import asyncio
import os
import sqlite3
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from yookassa import Configuration, Payment

# ────────────────────────────────────────────────
#                НАСТРОЙКИ
# ────────────────────────────────────────────────

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError(
        "❌ Токен бота не задан!\n\n"
        "На BotHost:\n"
        "1. Зайди в настройки бота\n"
        "2. Добавь переменную окружения BOT_TOKEN = твой_токен\n"
        "3. Перезапусти бота"
    )

# ЮKassa — тоже лучше вынести в переменные окружения
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET  = os.getenv("YOOKASSA_SECRET_KEY")

if YOOKASSA_SHOP_ID and YOOKASSA_SECRET:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET
else:
    print("Внимание: ЮKassa не настроена (нет shop_id или secret_key)")

# ────────────────────────────────────────────────

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_NAME = "yclients_clone.db"

# ====================== БАЗА ДАННЫХ ======================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY,
            name TEXT,
            duration INTEGER,
            price INTEGER
        );
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY,
            name TEXT,
            working_hours TEXT
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service_id INTEGER,
            staff_id INTEGER,
            date TEXT,
            time TEXT,
            status TEXT DEFAULT 'active',
            paid INTEGER DEFAULT 0,
            payment_id TEXT,
            reminded INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            role TEXT DEFAULT 'client',
            name TEXT,
            loyalty_points INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    ''')
    
    # Тестовые данные, если таблица пустая
    if not cur.execute("SELECT COUNT(*) FROM services").fetchone()[0]:
        cur.executemany(
            "INSERT INTO services (id, name, duration, price) VALUES (?,?,?,?)",
            [(1, "Стрижка", 60, 2500),
             (2, "Маникюр", 90, 3500),
             (3, "Массаж", 45, 4000)]
        )
        cur.executemany(
            "INSERT INTO staff (id, name, working_hours) VALUES (?,?,?)",
            [(1, "Анна", "09:00-20:00"),
             (2, "Мария", "10:00-19:00")]
        )
        cur.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('admin_pass', '12345')")
    
    conn.commit()
    conn.close()

# ====================== КЛАВИАТУРЫ ======================
def get_main_keyboard(role: str):
    if role == 'admin':
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Все записи", callback_data="admin_bookings")],
            [InlineKeyboardButton(text="➕ Добавить услугу", callback_data="add_service")],
            [InlineKeyboardButton(text="💳 Платежи", callback_data="admin_payments")]
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📋 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton(text="💎 Баллы", callback_data="loyalty")]
    ])

def get_calendar_keyboard():
    kb = []
    row = []
    today = datetime.now()
    for i in range(30):
        dt = today + timedelta(days=i)
        date_str = dt.strftime("%Y-%m-%d")
        display = dt.strftime("%d.%m")
        row.append(InlineKeyboardButton(text=display, callback_data=f"date_{date_str}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ====================== СОСТОЯНИЯ ======================
class Booking(StatesGroup):
    service = State()
    staff   = State()
    date    = State()
    time    = State()

class AdminLogin(StatesGroup):
    password = State()

# ====================== ФОНОВАЯ ЗАДАЧА — НАПОМИНАНИЯ ======================
async def reminders_background_task():
    while True:
        await asyncio.sleep(300)  # проверяем каждые 5 минут
        
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        soon_start = (now + timedelta(minutes=50)).strftime("%H:%M")
        soon_end   = (now + timedelta(minutes=70)).strftime("%H:%M")

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT b.id, b.user_id, b.date, b.time, s.name, st.name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN staff st ON b.staff_id = st.id
            WHERE b.status = 'active'
              AND b.reminded = 0
              AND b.date = ?
              AND b.time >= ? AND b.time <= ?
        """, (today, soon_start, soon_end)).fetchall()
        
        for bid, uid, d, t, serv, master in rows:
            try:
                await bot.send_message(
                    uid,
                    f"⏰ Напоминание!\n\nСегодня в {t}:\n{serv} у {master}\nНе опаздывайте! ✨"
                )
                cur.execute("UPDATE bookings SET reminded = 1 WHERE id = ?", (bid,))
            except:
                pass  # если пользователь заблокировал бота и т.д.
        
        conn.commit()
        conn.close()

# ====================== ХЕНДЛЕРЫ ======================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    uid = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)",
        (uid, message.from_user.full_name)
    )
    role = cur.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()[0]
    conn.close()

    await message.answer(
        "Добро пожаловать в YBotClients!\n\n"
        f"Ваша роль: {'Администратор 🛠' if role == 'admin' else 'Клиент 👤'}",
        reply_markup=get_main_keyboard(role)
    )

@dp.message(Command("admin"))
async def cmd_admin_login(message: types.Message, state: FSMContext):
    await message.answer("🔐 Введите пароль администратора:")
    await state.set_state(AdminLogin.password)

@dp.message(AdminLogin.password)
async def process_admin_password(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_NAME)
    saved_pass = conn.execute("SELECT value FROM admin_settings WHERE key = 'admin_pass'").fetchone()
    conn.close()

    if saved_pass and message.text == saved_pass[0]:
        conn = sqlite3.connect(DB_NAME)
        conn.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
        conn.close()
        await message.answer("✅ Доступ администратора открыт!", reply_markup=get_main_keyboard("admin"))
    else:
        await message.answer("❌ Неверный пароль")
    
    await state.clear()

# ────────────────────────────────────────────────
#                  ЗАПИСЬ КЛИЕНТА
# ────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "book")
async def booking_start(callback: types.CallbackQuery, state: FSMContext):
    conn = sqlite3.connect(DB_NAME)
    services = conn.execute("SELECT id, name, price FROM services ORDER BY name").fetchall()
    conn.close()

    if not services:
        await callback.message.edit_text("Услуг пока нет.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{name} — {price} ₽", callback_data=f"svc_{sid}")]
        for sid, name, price in services
    ])

    await callback.message.edit_text("Выберите услугу:", reply_markup=kb)
    await state.set_state(Booking.service)

@dp.callback_query(lambda c: c.data.startswith("svc_"))
async def booking_choose_staff(callback: types.CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split("_")[1])
    await state.update_data(service_id=service_id)

    conn = sqlite3.connect(DB_NAME)
    staff_list = conn.execute("SELECT id, name FROM staff").fetchall()
    conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"staff_{sid}")]
        for sid, name in staff_list
    ])

    await callback.message.edit_text("Выберите мастера:", reply_markup=kb)
    await state.set_state(Booking.staff)

@dp.callback_query(lambda c: c.data.startswith("staff_"))
async def booking_choose_date(callback: types.CallbackQuery, state: FSMContext):
    staff_id = int(callback.data.split("_")[1])
    await state.update_data(staff_id=staff_id)

    await callback.message.edit_text(
        "Выберите дату записи:",
        reply_markup=get_calendar_keyboard()
    )
    await state.set_state(Booking.date)

@dp.callback_query(lambda c: c.data.startswith("date_"))
async def booking_choose_time(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_", 1)[1]
    await state.update_data(date=date_str)

    data = await state.get_data()
    service_id = data["service_id"]
    staff_id   = data["staff_id"]

    conn = sqlite3.connect(DB_NAME)
    duration = conn.execute("SELECT duration FROM services WHERE id = ?", (service_id,)).fetchone()[0]
    booked_times = [row[0] for row in conn.execute(
        "SELECT time FROM bookings WHERE staff_id = ? AND date = ? AND status = 'active'",
        (staff_id, date_str)
    ).fetchall()]
    conn.close()

    # Генерируем слоты каждые 30 минут с 9:00 до 20:00
    possible_times = []
    current = datetime.strptime("09:00", "%H:%M")
    end = datetime.strptime("20:00", "%H:%M")
    while current < end:
        t_str = current.strftime("%H:%M")
        possible_times.append(t_str)
        current += timedelta(minutes=30)

    free_times = []
    for t in possible_times:
        # Очень упрощённая проверка (можно улучшить с учётом duration)
        if t not in booked_times:
            free_times.append(t)

    if not free_times:
        await callback.message.edit_text("На выбранную дату свободных окон нет.")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=f"time_{t}")]
        for t in free_times
    ])

    await callback.message.edit_text(f"Выберите время на {date_str}:", reply_markup=kb)
    await state.set_state(Booking.time)

@dp.callback_query(lambda c: c.data.startswith("time_"))
async def booking_confirm_and_pay(callback: types.CallbackQuery, state: FSMContext):
    time_str = callback.data.split("_", 1)[1]
    data = await state.get_data()
    uid = callback.from_user.id

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO bookings (user_id, service_id, staff_id, date, time)
        VALUES (?, ?, ?, ?, ?)
    """, (uid, data["service_id"], data["staff_id"], data["date"], time_str))

    booking_id = cur.lastrowid

    price = cur.execute(
        "SELECT price FROM services WHERE id = ?",
        (data["service_id"],)
    ).fetchone()[0]

    conn.commit()

    # Платёж
    if YOOKASSA_SHOP_ID and YOOKASSA_SECRET:
        try:
            payment = Payment.create({
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me"},
                "capture": True,
                "description": f"Запись #{booking_id}",
                "metadata": {"booking_id": str(booking_id)}
            }, uuid.uuid4().hex)

            cur.execute("UPDATE bookings SET payment_id = ? WHERE id = ?", (payment.id, booking_id))
            conn.commit()

            pay_url = payment.confirmation.confirmation_url

            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💳 Оплатить", url=pay_url),
                InlineKeyboardButton(text="Проверить позже", callback_data=f"checkpay_{booking_id}")
            ]])

            text = (
                f"Запись создана!\n\n"
                f"Дата: {data['date']}\n"
                f"Время: {time_str}\n"
                f"Сумма: {price} ₽\n\n"
                "Оплатите по кнопке ниже ↓"
            )
        except Exception as e:
            text = f"Ошибка создания платежа: {str(e)}\nЗапись всё равно создана."
            kb = None
    else:
        text = (
            f"Запись создана (без оплаты — ЮKassa не подключена)\n\n"
            f"Дата: {data['date']}   Время: {time_str}"
        )
        kb = None

    conn.close()

    await callback.message.edit_text(text, reply_markup=kb)
    await state.clear()

# ────────────────────────────────────────────────
#                  ПРОВЕРКА ОПЛАТЫ
# ────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data.startswith("checkpay_"))
async def check_payment_status(callback: types.CallbackQuery):
    try:
        booking_id = int(callback.data.split("_")[1])
        conn = sqlite3.connect(DB_NAME)
        payment_id = conn.execute("SELECT payment_id FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not payment_id or not payment_id[0]:
            await callback.answer("Платёж не найден", show_alert=True)
            conn.close()
            return

        payment = Payment.find_one(payment_id[0])

        if payment.status == "succeeded":
            cur = conn.cursor()
            cur.execute("UPDATE bookings SET paid = 1 WHERE id = ?", (booking_id,))
            cur.execute("""
                UPDATE users
                SET loyalty_points = loyalty_points + 10
                WHERE user_id = (SELECT user_id FROM bookings WHERE id = ?)
            """, (booking_id,))
            conn.commit()
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ Оплата подтверждена! +10 баллов начислено."
            )
        else:
            await callback.answer(f"Статус: {payment.status}\nОплата ещё не поступила.", show_alert=True)

        conn.close()
    except Exception as e:
        await callback.answer(f"Ошибка проверки: {str(e)}", show_alert=True)

# ────────────────────────────────────────────────
#                  МОИ ЗАПИСИ + ОТМЕНА
# ────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "my_bookings")
async def show_my_bookings(callback: types.CallbackQuery):
    uid = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    rows = conn.execute("""
        SELECT b.id, b.date, b.time, s.name, st.name, b.paid, b.status
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN staff st ON b.staff_id = st.id
        WHERE b.user_id = ?
        ORDER BY b.date DESC, b.time DESC
        LIMIT 10
    """, (uid,)).fetchall()
    conn.close()

    if not rows:
        await callback.message.edit_text("У вас пока нет записей.")
        return

    lines = []
    buttons = []
    for bid, date, time, serv, master, paid, status in rows:
        status_text = "Отменена" if status != "active" else ("Оплачено" if paid else "Ожидает оплаты")
        lines.append(f"{date} {time} • {serv} ({master}) — {status_text}")
        if status == "active":
            buttons.append([InlineKeyboardButton(text=f"Отменить #{bid}", callback_data=f"cancel_{bid}")])

    text = "Ваши записи:\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("cancel_"))
async def cancel_booking(callback: types.CallbackQuery):
    try:
        bid = int(callback.data.split("_")[1])
        conn = sqlite3.connect(DB_NAME)
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (bid,))
        conn.commit()
        conn.close()
        await callback.message.edit_text(callback.message.text + "\n\n❌ Запись отменена.")
    except:
        await callback.answer("Не удалось отменить", show_alert=True)

# ────────────────────────────────────────────────
#                  ЗАПУСК
# ────────────────────────────────────────────────

async def main():
    init_db()
    asyncio.create_task(reminders_background_task())
    await dp.start_polling(bot, allowed_updates=types.AllowedUpdates.MESSAGE + types.AllowedUpdates.CALLBACK_QUERY)

if __name__ == "__main__":
    asyncio.run(main())
