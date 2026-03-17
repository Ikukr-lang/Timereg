import asyncio
import logging
import os
import json
from datetime import datetime, timedelta, date, time

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
            specialists TEXT DEFAULT '[]',
            appointments TEXT DEFAULT '[]'
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

# ====================== КЛАВИАТУРЫ ======================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать свою компанию", callback_data="create_company")]
    ])

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if message.text and "comp_" in message.text:
        company_id = int(message.text.split("comp_")[1])
        await show_company(message, company_id)
        return

    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",
        caption="👋 Добро пожаловать в **Time Reg** — сервис онлайн-записи!\n\n"
                "Создайте свою компанию или запишитесь по ссылке.",
        reply_markup=main_menu()
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
        "Теперь добавляйте **услуги** по одной строке в формате:\n"
        "`Название | длительность (мин) | цена`\n"
        "Пример: Массаж спины | 60 | 2500\n\n"
        "Напишите **готово**, когда закончите."
    )
    await state.set_state(CompanyCreation.services)

@dp.message(CompanyCreation.services)
async def add_service(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == "готово":
        await message.answer(
            "Отлично! Теперь добавляйте **специалистов**.\n"
            "Формат: `Фамилия Имя`\n"
            "Можно отправить фото перед текстом.\n\n"
            "Напишите **готово**, когда закончите."
        )
        await state.set_state(CompanyCreation.specialists)
        return

    try:
        parts = [p.strip() for p in message.text.split("|")]
        service = {"name": parts[0], "duration": int(parts[1]), "price": int(parts[2])}
        services = data.get("services", [])
        services.append(service)
        await state.update_data(services=services)
        await message.answer(f"✅ Добавлена услуга: {service['name']}")
    except:
        await message.answer("❌ Неверный формат. Используйте: Название | минуты | цена")

@dp.message(CompanyCreation.specialists)
async def add_specialist(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == "готово":
        await save_company_and_give_link(message, state)
        await state.clear()
        return

    photo = message.photo[-1].file_id if message.photo else None
    spec = {"name": message.text.strip(), "photo": photo}
    specialists = data.get("specialists", [])
    specialists.append(spec)
    await state.update_data(specialists=specialists)
    await message.answer(f"✅ Специалист добавлен: {spec['name']}")

async def save_company_and_give_link(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute(
        "UPDATE companies SET services = ?, specialists = ? WHERE company_id = ?",
        (json.dumps(data["services"]), json.dumps(data["specialists"]), data["company_id"])
    )
    await db.commit()

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=comp_{data['company_id']}"

    await message.answer(
        f"🎉 Компания успешно создана!\n\n"
        f"🔗 Ваша ссылка для записи:\n`{link}`\n\n"
        f"Отправьте её клиентам — они смогут выбрать услугу, специалиста и время.",
        parse_mode="Markdown"
    )

# ====================== ПОКАЗ КОМПАНИИ ДЛЯ ЗАПИСИ ======================
async def show_company(message: Message, company_id: int):
    async with db.execute("SELECT name, photo, services, specialists FROM companies WHERE company_id = ?", (company_id,)) as cur:
        row = await cur.fetchone()
        if not row:
            await message.answer("Компания не найдена.")
            return

        name, photo, services_json, specialists_json = row
        services = json.loads(services_json) if services_json else []
        specialists = json.loads(specialists_json) if specialists_json else []

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s["name"], callback_data=f"choose_service_{company_id}_{i}")]
            for i, s in enumerate(services)
        ])

        await message.answer_photo(
            photo=photo,
            caption=f"🏢 {name}\n\nВыберите услугу:",
            reply_markup=kb
        )

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    print("✅ Сервис онлайн-записи Time Reg запущен успешно!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
