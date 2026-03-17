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
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

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
            subscription_end TEXT,
            max_specialists INTEGER DEFAULT 1,
            specialists TEXT DEFAULT '[]',
            services TEXT DEFAULT '[]',
            bindings TEXT DEFAULT '[]',
            appointments TEXT DEFAULT '[]'
        )
    """)
    await db.commit()

# ====================== СОСТОЯНИЯ ======================
class CreateCompany(StatesGroup):
    name = State()
    photo = State()
    description = State()

# ====================== КЛАВИАТУРА ПОДПИСОК ======================
def subscription_keyboard(company_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней — бесплатно", callback_data=f"sub_free_{company_id}")],
        [InlineKeyboardButton(text="1 специалист — ~150₽/мес", callback_data=f"sub_1_{company_id}")],
        [InlineKeyboardButton(text="2-3 специалиста — ~250₽/мес", callback_data=f"sub_3_{company_id}")],
        [InlineKeyboardButton(text="4-5 специалистов — ~350₽/мес", callback_data=f"sub_5_{company_id}")],
        [InlineKeyboardButton(text="6-7 специалистов — ~450₽/мес", callback_data=f"sub_7_{company_id}")],
        [InlineKeyboardButton(text="8-10 специалистов — ~550₽/мес", callback_data=f"sub_10_{company_id}")],
        [InlineKeyboardButton(text="11-15 специалистов — ~750₽/мес", callback_data=f"sub_15_{company_id}")],
        [InlineKeyboardButton(text="16-20 специалистов — ~1000₽/мес", callback_data=f"sub_20_{company_id}")],
    ])

# ====================== СТАРТ ======================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Создать компанию", callback_data="create_company")],
        [InlineKeyboardButton(text="🛠 Поддержка", callback_data="support")]
    ])
    
    await message.answer_photo(
        photo="https://i.imgur.com/TIME_REG_LOGO.png",
        caption="👋 Добро пожаловать в **Time Reg**!\n\n"
                "Сервис онлайн-записи к специалистам.",
        reply_markup=kb
    )

# ====================== СОЗДАНИЕ КОМПАНИИ ======================
@dp.callback_query(F.data == "create_company")
async def start_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название вашей компании:")
    await state.set_state(CreateCompany.name)

@dp.message(CreateCompany.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отправьте фото компании (будет отображаться кругом):")
    await state.set_state(CreateCompany.photo)

@dp.message(CreateCompany.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Введите описание компании:")
    await state.set_state(CreateCompany.description)

@dp.message(CreateCompany.description)
async def process_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    
    async with db.execute(
        """INSERT INTO companies 
           (owner_id, name, photo, description, subscription_end, max_specialists)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (message.from_user.id, data["name"], data["photo"], message.text, 
         (datetime.now() + timedelta(days=7)).isoformat())
    ) as cur:
        company_id = cur.lastrowid
    await db.commit()

    await message.answer(
        f"✅ Компания «{data['name']}» успешно создана!\n\n"
        f"Выберите тариф для активации:",
        reply_markup=subscription_keyboard(company_id)
    )
    await state.clear()

# ====================== ОБРАБОТКА ПОДПИСКИ ======================
@dp.callback_query(F.data.startswith("sub_"))
async def activate_subscription(callback: CallbackQuery):
    _, plan, company_id = callback.data.split("_")
    company_id = int(company_id)

    months = 1
    if plan == "free":
        days = 7
        max_spec = 1
    else:
        days = 30
        max_spec = {"1":1, "3":3, "5":5, "7":7, "10":10, "15":15, "20":20}.get(plan, 1)

    end_date = datetime.now() + timedelta(days=days)

    await db.execute(
        "UPDATE companies SET subscription_end = ?, max_specialists = ? WHERE company_id = ?",
        (end_date.isoformat(), max_spec, company_id)
    )
    await db.commit()

    await callback.message.edit_text(
        f"✅ Подписка активирована!\n\n"
        f"Действует до: {end_date.strftime('%d.%m.%Y')}\n"
        f"Максимум специалистов: {max_spec}\n\n"
        f"Теперь доступна админ-панель вашей компании."
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Специалисты", callback_data=f"adm_spec_{company_id}")],
        [InlineKeyboardButton(text="🛍 Услуги", callback_data=f"adm_serv_{company_id}")],
        [InlineKeyboardButton(text="🏪 Витрина", callback_data=f"adm_vit_{company_id}")],
        [InlineKeyboardButton(text="🔗 Привязка услуг", callback_data=f"adm_bind_{company_id}")],
        [InlineKeyboardButton(text="📅 Записи", callback_data=f"adm_app_{company_id}")],
        [InlineKeyboardButton(text="🔗 Ссылка на компанию", callback_data=f"get_link_{company_id}")],
    ])
    
    await callback.message.answer("🛠 Админ-панель компании:", reply_markup=admin_kb)

# ====================== ССЫЛКА НА КОМПАНИЮ ======================
@dp.callback_query(F.data.startswith("get_link_"))
async def send_link(callback: CallbackQuery):
    company_id = int(callback.data.split("_")[2])
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=comp_{company_id}"
    await callback.message.answer(
        f"🔗 Ссылка на вашу компанию:\n\n`{link}`\n\n"
        f"Отправьте её клиентам для записи.", 
        parse_mode="Markdown"
    )

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    print("✅ Time Reg бот успешно запущен на Bothost!")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
