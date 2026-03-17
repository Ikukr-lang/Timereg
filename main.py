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
            subscription_end TEXT,
            max_specialists INTEGER DEFAULT 5
        )
    """)
    await db.commit()

# ====================== FSM СОСТОЯНИЯ ======================
class CreateCompany(StatesGroup):
    name = State()
    photo = State()
    description = State()
    waiting_for_services = State()   # добавление услуг
    waiting_for_specialists = State() # добавление специалистов

# ====================== КЛАВИАТУРЫ ======================
def finish_keyboard(company_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Завершить создание и получить ссылку", callback_data=f"finish_create_{company_id}")]
    ])

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать компанию", callback_data="create_company")]
    ])
    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",
        caption="👋 Добро пожаловать в **Time Reg**!\nСервис онлайн-записи.",
        reply_markup=kb
    )

# ====================== СОЗДАНИЕ КОМПАНИИ ======================
@dp.callback_query(F.data == "create_company")
async def start_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название компании:")
    await state.set_state(CreateCompany.name)

@dp.message(CreateCompany.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text, services=[], specialists=[])
    await message.answer("Отправьте фото компании:")
    await state.set_state(CreateCompany.photo)

@dp.message(CreateCompany.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Введите описание компании:")
    await state.set_state(CreateCompany.description)

@dp.message(CreateCompany.description)
async def process_description(message: Message, state: FSMContext):
    data = await state.get_data()
    
    async with db.execute(
        """INSERT INTO companies (owner_id, name, photo, description, subscription_end)
           VALUES (?, ?, ?, ?, ?)""",
        (message.from_user.id, data['name'], data['photo'], message.text,
         (datetime.now() + timedelta(days=7)).isoformat())
    ) as cur:
        company_id = cur.lastrowid
    await db.commit()

    await state.update_data(company_id=company_id)
    
    await message.answer(
        "✅ Компания создана!\n\n"
        "Теперь добавляйте **услуги**.\n\n"
        "Отправляйте в формате:\n"
        "`Название услуги | 60 | 1500`\n"
        "(где 60 — длительность в минутах, 1500 — цена в рублях)\n\n"
        "Когда закончите — напишите слово: **готово**",
        parse_mode="Markdown"
    )
    await state.set_state(CreateCompany.waiting_for_services)

# ====================== ДОБАВЛЕНИЕ УСЛУГ ======================
@dp.message(CreateCompany.waiting_for_services)
async def add_service(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == "готово":
        await message.answer(
            "Отлично! Теперь добавляйте **специалистов**.\n\n"
            "Отправляйте в формате:\n"
            "`Фамилия Имя | @username` или просто `Фамилия Имя`\n"
            "Можно отправить фото специалиста перед текстом.\n\n"
            "Когда закончите — напишите **готово**"
        )
        await state.set_state(CreateCompany.waiting_for_specialists)
        return

    try:
        name, duration, price = [x.strip() for x in message.text.split("|")]
        duration = int(duration)
        price = int(price)
        
        services = data.get("services", [])
        services.append({"name": name, "duration": duration, "price": price})
        await state.update_data(services=services)

        await message.answer(f"✅ Услуга добавлена:\n{name} — {duration} мин — {price} ₽")
    except:
        await message.answer("❌ Неверный формат. Используйте:\nНазвание | длительность | цена")

# ====================== ДОБАВЛЕНИЕ СПЕЦИАЛИСТОВ ======================
@dp.message(CreateCompany.waiting_for_specialists)
async def add_specialist(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == "готово":
        # Сохраняем всё в базу
        await db.execute(
            "UPDATE companies SET services = ?, specialists = ? WHERE company_id = ?",
            (json.dumps(data["services"]), json.dumps(data["specialists"]), data["company_id"])
        )
        await db.commit()

        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=comp_{data['company_id']}"
        
        await message.answer(
            f"🎉 Компания полностью создана!\n\n"
            f"🔗 **Ссылка для клиентов**:\n`{link}`\n\n"
            f"Отправьте эту ссылку тем, кто хочет записаться.\n"
            f"Они увидят ваши услуги, специалистов и смогут выбрать время.",
            parse_mode="Markdown"
        )
        await state.clear()
        return

    # Пока простое добавление (фото + текст)
    photo = message.photo[-1].file_id if message.photo else None
    name = message.text.strip()

    specialists = data.get("specialists", [])
    specialists.append({"name": name, "photo": photo})
    await state.update_data(specialists=specialists)

    await message.answer(f"✅ Специалист добавлен: {name}")

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    print("✅ Time Reg бот запущен! Процесс создания компании обновлён.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
