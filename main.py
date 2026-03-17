import asyncio
import logging
import os
import json
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# ====================== НАСТРОЙКИ ======================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = None
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    global db
    db = await aiosqlite.connect("timereg.db")
    await db.execute("PRAGMA journal_mode=WAL")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
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
            max_specialists INTEGER DEFAULT 1,
            specialists TEXT DEFAULT '[]',   -- JSON список специалистов
            services TEXT DEFAULT '[]',      -- JSON список услуг
            bindings TEXT DEFAULT '[]',      -- JSON привязки
            appointments TEXT DEFAULT '[]'   -- JSON записи
        )
    """)
    await db.commit()

# ====================== СОСТОЯНИЯ ======================
class CreateCompany(StatesGroup):
    name = State()
    photo = State()
    description = State()

# ====================== СЧЁТЧИК ======================
async def get_start_count():
    async with db.execute("SELECT SUM(start_count) FROM users") as cur:
        row = await cur.fetchone()
        return row[0] if row else 0

# ====================== КЛАВИАТУРА ПОДПИСОК ======================
def get_subscription_keyboard(company_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней — бесплатно (тест)", callback_data=f"sub_free_{company_id}")],
        [InlineKeyboardButton(text="1 специалист — 150₽/мес", callback_data=f"sub_1_{company_id}")],
        [InlineKeyboardButton(text="2-3 специалиста — 250₽/мес", callback_data=f"sub_3_{company_id}")],
        [InlineKeyboardButton(text="4-5 специалистов — 350₽/мес", callback_data=f"sub_5_{company_id}")],
        [InlineKeyboardButton(text="6-7 специалистов — 450₽/мес", callback_data=f"sub_7_{company_id}")],
        [InlineKeyboardButton(text="8-10 специалистов — 550₽/мес", callback_data=f"sub_10_{company_id}")],
        [InlineKeyboardButton(text="11-15 специалистов — 750₽/мес", callback_data=f"sub_15_{company_id}")],
        [InlineKeyboardButton(text="16-20 специалистов — 1000₽/мес", callback_data=f"sub_20_{company_id}")],
    ])
    return kb

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    await db.execute("UPDATE users SET start_count = start_count + 1 WHERE user_id = ?", (message.from_user.id,))
    await db.commit()

    count = await get_start_count()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать компанию", callback_data="create_company")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ])

    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",
        caption=f"👋 Добро пожаловать в **Time Reg**!\n\n"
                f"📊 Пользователей запустили бота: **{count}**",
        reply_markup=kb
    )

# ====================== СОЗДАТЬ КОМПАНИЮ ======================
@dp.callback_query(F.data == "create_company")
async def start_create_company(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название вашей компании:")
    await state.set_state(CreateCompany.name)

@dp.message(CreateCompany.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отправьте фото компании (будет отображаться в кружке):")
    await state.set_state(CreateCompany.photo)

@dp.message(CreateCompany.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo=photo_id)
    await message.answer("Введите описание компании:")
    await state.set_state(CreateCompany.description)

@dp.message(CreateCompany.description)
async def process_description(message: Message, state: FSMContext):
    data = await state.get_data()
    
    async with db.execute(
        """INSERT INTO companies 
           (owner_id, name, photo, description, subscription_end, max_specialists)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (message.from_user.id, data['name'], data['photo'], message.text,
         str(datetime.now() + timedelta(days=7)), 1)
    ) as cursor:
        company_id = cursor.lastrowid
    
    await db.commit()

    await message.answer(
        f"✅ Компания «{data['name']}» создана!\n\n"
        f"Выберите подписку для активации полного функционала:",
        reply_markup=get_subscription_keyboard(company_id)
    )
    await state.clear()

# ====================== ОБРАБОТКА ПОДПИСОК ======================
@dp.callback_query(F.data.startswith("sub_"))
async def process_subscription(callback: CallbackQuery):
    parts = callback.data.split("_")
    plan = parts[1]
    company_id = int(parts[2])

    days = 7 if plan == "free" else 30
    end_date = datetime.now() + timedelta(days=days)

    # Определяем максимальное количество специалистов
    max_spec = {
        "free": 1, "1": 1, "3": 3, "5": 5, "7": 7,
        "10": 10, "15": 15, "20": 20
    }.get(plan, 1)

    await db.execute(
        "UPDATE companies SET subscription_end = ?, max_specialists = ? WHERE company_id = ?",
        (end_date.isoformat(), max_spec, company_id)
    )
    await db.commit()

    await callback.message.edit_text(
        f"✅ Подписка активирована!\n\n"
        f"Действует до: <b>{end_date.strftime('%d.%m.%Y %H:%M')}</b>\n"
        f"Максимум специалистов: <b>{max_spec}</b>\n\n"
        f"Теперь у вас есть полная админ-панель компании №{company_id}"
    )

    # Показываем админ-панель
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Специалисты", callback_data=f"admin_spec_{company_id}")],
        [InlineKeyboardButton(text="🛍 Услуги", callback_data=f"admin_services_{company_id}")],
        [InlineKeyboardButton(text="🏪 Витрина компании", callback_data=f"admin_vitrine_{company_id}")],
        [InlineKeyboardButton(text="🔗 Привязка услуг к специалистам", callback_data=f"admin_bind_{company_id}")],
        [InlineKeyboardButton(text="📅 Записи", callback_data=f"admin_appointments_{company_id}")],
        [InlineKeyboardButton(text="🔗 Получить ссылку на компанию", callback_data=f"get_link_{company_id}")],
    ])
    await callback.message.answer("🛠 Админ-панель компании:", reply_markup=admin_kb)

# ====================== ЗАГЛУШКИ АДМИН-ПАНЕЛИ (готовы к расширению) ======================
@dp.callback_query(F.data.startswith("admin_"))
async def admin_panel(callback: CallbackQuery):
    await callback.answer("Функция в разработке. Скоро будет полностью работать.", show_alert=True)

@dp.callback_query(F.data.startswith("get_link_"))
async def get_company_link(callback: CallbackQuery):
    company_id = int(callback.data.split("_")[2])
    link = f"https://t.me/{(await bot.get_me()).username}?start=comp_{company_id}"
    await callback.message.answer(
        f"🔗 Ссылка на вашу компанию:\n\n"
        f"`{link}`\n\n"
        f"Отправьте её клиентам — они смогут записаться.",
        parse_mode="Markdown"
    )

# ====================== ПРОВЕРКА ПОДПИСОК (каждый час)
