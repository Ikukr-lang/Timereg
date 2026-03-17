import asyncio
import logging
import os
import json
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = None

logging.basicConfig(level=logging.INFO)

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    global db
    db = await aiosqlite.connect("timereg.db")
    await db.execute("PRAGMA journal_mode=WAL")
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT,
            photo TEXT,
            description TEXT,
            services TEXT DEFAULT '[]',
            specialists TEXT DEFAULT '[]'
        )
    """)
    await db.commit()

# ====================== СОСТОЯНИЯ ======================
class CompanyCreation(StatesGroup):
    name = State()
    photo = State()
    description = State()
    services = State()
    specialists = State()

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать свою компанию", callback_data="create_company")]
    ])
    
    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",
        caption="👋 Добро пожаловать в **Time Reg** — сервис онлайн-записи!\n\n"
                "Нажмите кнопку ниже, чтобы создать компанию.",
        reply_markup=kb
    )

# ====================== СОЗДАНИЕ КОМПАНИИ ======================
@dp.callback_query(F.data == "create_company")
async def start_creation(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название компании:")
    await state.set_state(CompanyCreation.name)

@dp.message(CompanyCreation.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text, services=[], specialists=[])
    await message.answer("Отправьте фото компании:")
    await state.set_state(CompanyCreation.photo)

@dp.message(CompanyCreation.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Введите описание компании:")
    await state.set_state(CompanyCreation.description)

@dp.message(CompanyCreation.description)
async def process_description(message: Message, state: FSMContext):
    data = await state.get_data()
    
    async with db.execute(
        "INSERT INTO companies (owner_id, name, photo, description) VALUES (?, ?, ?, ?)",
        (message.from_user.id, data["name"], data["photo"], message.text)
    ) as cur:
        company_id = cur.lastrowid
    await db.commit()

    await state.update_data(company_id=company_id)
    await message.answer(
        "✅ Компания создана!\n\n"
        "Добавляйте услуги по одной в формате:\n"
        "`Название | длительность в минутах | цена`\n"
        "Пример: Массаж | 60 | 2500\n\n"
        "Когда все услуги добавите — напишите слово **готово**"
    )
    await state.set_state(CompanyCreation.services)

# ====================== ДОБАВЛЕНИЕ УСЛУГ ======================
@dp.message(CompanyCreation.services)
async def add_service(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if message.text.lower().strip() == "готово":
        await message.answer(
            "Хорошо! Теперь добавляйте специалистов.\n\n"
            "Формат: Фамилия Имя\n"
            "Можно отправить фото специалиста перед текстом.\n\n"
            "Когда закончите — напишите **готово**"
        )
        await state.set_state(CompanyCreation.specialists)
        return

    try:
        name, duration, price = [x.strip() for x in message.text.split("|")]
        service = {"name": name, "duration": int(duration), "price": int(price)}
        
        services = data.get("services", [])
        services.append(service)
        await state.update_data(services=services)
        
        await message.answer(f"✅ Услуга добавлена: {name} ({duration} мин, {price} ₽)")
    except:
        await message.answer("❌ Неверный формат!\nИспользуйте: Название | минуты | цена")

# ====================== ДОБАВЛЕНИЕ СПЕЦИАЛИСТОВ ======================
@dp.message(CompanyCreation.specialists)
async def add_specialist(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if message.text.lower().strip() == "готово":
        await finish_creation(message, state)
        await state.clear()
        return

    photo = message.photo[-1].file_id if message.photo else None
    specialist = {"name": message.text.strip(), "photo": photo}
    
    specialists = data.get("specialists", [])
    specialists.append(specialist)
    await state.update_data(specialists=specialists)
    
    await message.answer(f"✅ Специалист добавлен: {specialist['name']}")

async def finish_creation(message: Message, state: FSMContext):
    data = await state.get_data()
    
    await db.execute(
        "UPDATE companies SET services = ?, specialists = ? WHERE company_id = ?",
        (json.dumps(data.get("services", [])), json.dumps(data.get("specialists", [])), data["company_id"])
    )
    await db.commit()

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=comp_{data['company_id']}"

    await message.answer(
        f"🎉 Компания успешно создана!\n\n"
        f"🔗 Ссылка для клиентов:\n`{link}`\n\n"
        f"Теперь другие пользователи могут переходить по ней и записываться.",
        parse_mode="Markdown"
    )

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    print("✅ Time Reg бот запущен!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
