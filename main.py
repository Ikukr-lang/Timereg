import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = None

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    global db
    db = await aiosqlite.connect("timereg.db")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT,
            photo TEXT,
            description TEXT,
            subscription_end TEXT,
            max_specialists INTEGER DEFAULT 1
        )
    """)
    await db.commit()

# ====================== СОСТОЯНИЯ ======================
class CreateCompany(StatesGroup):
    name = State()
    photo = State()
    description = State()

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать компанию", callback_data="create_company")]
    ])
    await message.answer("👋 Time Reg бот запущен!\n\nНажмите кнопку ниже.", reply_markup=kb)

@dp.callback_query(F.data == "create_company")
async def create_company(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название компании:")
    await state.set_state(CreateCompany.name)

# Заглушка — дальше будем расширять
@dp.message(CreateCompany.name)
async def process_name(message: Message, state: FSMContext):
    await message.answer("✅ Название сохранено (пока заглушка).\n\nПодписки и админ-панель будут добавлены в следующем обновлении.")
    await state.clear()

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    print("✅ Бот запущен (облегчённая версия)")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
