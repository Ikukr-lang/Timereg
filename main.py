import asyncio
import logging
import os
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

# ====================== ЗАГРУЗКА ТОКЕНА ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = None
scheduler = AsyncIOScheduler()   # ← Создаём планировщик глобально

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
            specialists TEXT,
            services TEXT,
            bindings TEXT,
            appointments TEXT
        )
    """)
    await db.commit()

# ====================== СОСТОЯНИЯ ======================
class CreateCompany(StatesGroup):
    name = State()
    photo = State()
    description = State()

# ====================== СЧЁТЧИК ПОЛЬЗОВАТЕЛЕЙ ======================
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

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать компанию", callback_data="create_company")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ])

    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",   # ← Замените на свой логотип
        caption=f"👋 Добро пожаловать в **Time Reg**!\n\n"
                f"📊 Пользователей, запустивших бота: **{count}**\n\n"
                f"Сервис онлайн-записи к специалистам.",
        reply_markup=kb
    )

# ====================== ПЛАНИРОВЩИК (теперь запускается правильно) ======================
async def check_subscriptions():
    if db is None:
        return
    async with db.execute("SELECT company_id, subscription_end FROM companies") as cursor:
        async for row in cursor:
            try:
                end_date = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
                if end_date < datetime.now():
                    # Здесь будет отключение компании
                    pass
                elif end_date < datetime.now() + timedelta(days=1):
                    # Уведомление за день до окончания
                    pass
            except:
                pass

# ====================== ЗАПУСК БОТА ======================
async def main():
    await init_db()
    
    # Запускаем планировщик ТОЛЬКО после создания event loop
    scheduler.add_job(check_subscriptions, "interval", hours=1, id="check_subs")
    scheduler.start()

    print("✅ Бот Time Reg успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
