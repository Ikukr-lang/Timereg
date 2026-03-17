import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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
    raise ValueError("❌ BOT_TOKEN не найден в файле .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = None

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    global db
    db = await aiosqlite.connect("timereg.db")
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
            subscription_end TEXT
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

# ====================== СТАРТ БОТА ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    await db.execute(
        "UPDATE users SET start_count = start_count + 1 WHERE user_id = ?",
        (message.from_user.id,)
    )
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

# ====================== ПРОВЕРКА ПОДПИСОК ======================
async def check_subscriptions():
    if not db:
        return
    async with db.execute("SELECT company_id, subscription_end FROM companies") as cur:
        async for row in cur:
            try:
                end = datetime.fromisoformat(str(row[1]))
                if end < datetime.now():
                    print(f"Компания {row[0]} — подписка истекла")
                elif end < datetime.now() + timedelta(days=1):
                    print(f"Компания {row[0]} — заканчивается через день")
            except:
                pass

# ====================== ЗАПУСК ======================
async def main():
    await init_db()

    # Запускаем планировщик ТОЛЬКО здесь
    scheduler.add_job(check_subscriptions, trigger="interval", hours=1)
    scheduler.start()

    print("✅ Time Reg бот успешно запущен на Bothost!")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
