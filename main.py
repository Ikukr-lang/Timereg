import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

bot = Bot(token="ТОКЕН_ИЗ_ENV")  # или os.getenv
dp = Dispatcher(storage=MemoryStorage())
db = None

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    global db
    db = await aiosqlite.connect("timereg.db")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            start_count INTEGER DEFAULT 0
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT,
            photo TEXT,
            description TEXT,
            subscription_end TEXT,
            specialists TEXT,  -- JSON
            services TEXT,     -- JSON
            bindings TEXT,     -- JSON
            appointments TEXT  -- JSON
        )
    """)
    await db.commit()

# ====================== СОСТОЯНИЯ ======================
class CreateCompany(StatesGroup):
    name = State()
    photo = State()
    description = State()

# ====================== ГЛОБАЛЬНЫЙ СЧЁТЧИК ======================
async def get_start_count():
    async with db.execute("SELECT SUM(start_count) FROM users") as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await db.execute("UPDATE users SET start_count = start_count + 1 WHERE user_id = ?", (user_id,))
    await db.commit()

    count = await get_start_count()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать компанию", callback_data="create_company")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ])

    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",  # замените на свою картинку
        caption=f"👋 Добро пожаловать в **Time Reg**!\n\n"
                f"📊 Пользователей, запустивших бота: **{count}**\n\n"
                f"Сервис для записи к специалистам с автоматическим расписанием.",
        reply_markup=keyboard
    )

# ====================== СОЗДАТЬ КОМПАНИЮ ======================
@dp.callback_query(F.data == "create_company")
async def start_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название компании:")
    await state.set_state(CreateCompany.name)

@dp.message(CreateCompany.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отправьте фото компании (круглое):")
    await state.set_state(CreateCompany.photo)

@dp.message(CreateCompany.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo = message.photo[-1].file_id
    await state.update_data(photo=photo)
    await message.answer("Введите описание компании:")
    await state.set_state(CreateCompany.description)

@dp.message(CreateCompany.description)
async def process_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    async with db.execute(
        "INSERT INTO companies (owner_id, name, photo, description, subscription_end) VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, data['name'], data['photo'], message.text, str(datetime.now() + timedelta(days=7)))
    ) as cursor:
        company_id = cursor.lastrowid
    await db.commit()

    await message.answer(f"✅ Компания создана!\nID: {company_id}\n\n"
                         f"Тестовый период 7 дней бесплатно.\n\n"
                         f"Выберите тариф ниже:")

    sub_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней — бесплатно", callback_data=f"sub_free_{company_id}")],
        [InlineKeyboardButton(text="1 специалист ~150₽/мес", callback_data=f"sub_1_{company_id}")],
        # ... добавьте все остальные тарифы аналогично
    ])
    await message.answer("Выберите подписку:", reply_markup=sub_keyboard)

# ====================== ТАРИФЫ (пример одного, остальные аналогично) ======================
@dp.callback_query(F.data.startswith("sub_"))
async def choose_subscription(callback: CallbackQuery):
    # Здесь логика оплаты (Telegram Payments или YooKassa)
    # После успешной оплаты обновляете subscription_end и даёте доступ к админке
    await callback.message.answer("✅ Оплата прошла! Подписка активна до 17.04.2026\n\n"
                                  "Теперь у вас есть админ-панель:")

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Специалисты", callback_data="admin_specialists")],
        [InlineKeyboardButton(text="🛍 Услуги", callback_data="admin_services")],
        [InlineKeyboardButton(text="🏪 Витрина", callback_data="admin_vitrine")],
        [InlineKeyboardButton(text="🔗 Привязка услуг", callback_data="admin_bindings")],
        [InlineKeyboardButton(text="📅 Записи", callback_data="admin_appointments")],
        [InlineKeyboardButton(text="🔗 Ссылка на компанию", callback_data="get_link")]
    ])
    await callback.message.answer("Админ-панель:", reply_markup=admin_kb)

# ====================== АДМИН-ПАНЕЛЬ (заглушки, расширяйте) ======================
@dp.callback_query(F.data == "admin_specialists")
async def specialists(callback: CallbackQuery):
    await callback.message.answer("👥 Здесь можно добавлять/редактировать специалистов\n"
                                  "Фото в кружке, ФИО, график работы (будни/выходные)")

# Аналогично для остальных кнопок...

# ====================== ССЫЛКА НА КОМПАНИЮ ======================
@dp.callback_query(F.data == "get_link")
async def get_company_link(callback: CallbackQuery):
    company_id = 1  # заменить на реальный
    link = f"https://t.me/timereg_bot?start=comp_{company_id}"
    await callback.message.answer(f"🔗 Ссылка для клиентов:\n`{link}`\n\n"
                                  f"Перешлите её клиентам — они попадут прямо в вашу витрину.")

# ====================== ФОНОВЫЙ КОНТРОЛЬ ПОДПИСОК ======================
scheduler = AsyncIOScheduler()

async def check_subscriptions():
    async with db.execute("SELECT company_id, subscription_end FROM companies") as cursor:
        async for row in cursor:
            end = datetime.fromisoformat(row[1])
            if end < datetime.now():
                # отключить функционал
                pass
            elif end < datetime.now() + timedelta(days=1):
                # уведомить владельца
                pass

scheduler.add_job(check_subscriptions, "interval", hours=1)
scheduler.start()

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
