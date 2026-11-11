"""Telegram bot (aiogram 3). Ishga tushirish:  python -m app.bot.main

- /start: botda ro'yxatdan o'tish, saytda ro'yxatdan o'tish yoki mavjud akkauntni ulash
- /navbat: shifokor -> kun -> vaqt tugmalari. Vaqt bosilsa navbat band bo'ladi (CRM'da ko'rinadi)
- /my: navbatlarni ko'rish va bekor qilish, /parol: sayt uchun yangi parol
DB bilan ishlash sinxron, shuning uchun asyncio.to_thread orqali chaqiriladi.
"""
import asyncio
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Appointment, AppointmentStatus, Doctor, Role, User
from app.schemas import normalize_phone
from app.services.appointments import BookingError, book as book_appointment, cancel_appointment
from app.services.messages import format_appointment
from app.services.slots import get_free_slots

# Sayt manzili (.env da SITE_URL=...). Joylashtirgandan (deploy) keyin haqiqiy manzilni yozasiz.
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000/app/")
DAYS_AHEAD = 14  # navbat olish uchun necha kun oldinga qaraymiz
WD = ["Dush", "Sesh", "Chor", "Pay", "Juma", "Shan", "Yak"]

router = Router()


class Reg(StatesGroup):
    name = State()
    phone = State()
    password = State()


# ---------- sinxron DB yordamchilari ----------
def _unlink_chat(db, chat_id: int) -> None:
    # bitta Telegram akkaunt faqat bitta foydalanuvchiga bog'lanadi
    db.execute(update(User).where(User.telegram_chat_id == chat_id).values(telegram_chat_id=None))


def _linked_name(chat_id: int) -> str | None:
    with SessionLocal() as db:
        return db.scalar(select(User.full_name).where(User.telegram_chat_id == chat_id))


def _role(chat_id: int) -> Role | None:
    with SessionLocal() as db:
        return db.scalar(select(User.role).where(User.telegram_chat_id == chat_id))


def _link_chat(phone: str, chat_id: int) -> str | None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == phone))
        if not user:
            return None
        _unlink_chat(db, chat_id)
        user.telegram_chat_id = chat_id
        db.commit()
        return user.full_name


def _register(phone: str, name: str, password: str, chat_id: int) -> bool:
    """Yangi bemorni yaratadi va Telegramni ulaydi. Raqam band bo'lsa False."""
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.phone == phone)):
            return False
        _unlink_chat(db, chat_id)
        db.add(User(phone=phone, full_name=name, role=Role.patient,
                    password_hash=hash_password(password), telegram_chat_id=chat_id))
        db.commit()
    return True


def _reset_password(chat_id: int) -> str | None:
    """Faqat Telegram ulangan bemor akkaunti uchun. Xodimlar parolini terminaldan tiklaydi."""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_chat_id == chat_id,
                                            User.role == Role.patient))
        if not user:
            return None
        temp = secrets.token_urlsafe(6)
        user.password_hash = hash_password(temp)
        db.commit()
        return temp


def _upcoming(chat_id: int) -> list[tuple[int, str]] | None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            return None
        appts = db.scalars(
            select(Appointment)
            .options(selectinload(Appointment.doctor).selectinload(Doctor.user),
                     selectinload(Appointment.doctor).selectinload(Doctor.cabinet))
            .where(Appointment.patient_id == user.id,
                   Appointment.status == AppointmentStatus.booked,
                   Appointment.start_at > datetime.now(timezone.utc))
            .order_by(Appointment.start_at)
        ).all()
        return [(a.id, format_appointment(a)) for a in appts]


def _cancel(appt_id: int, chat_id: int) -> tuple[bool, str]:
    with SessionLocal() as db:
        appt = db.get(Appointment, appt_id)
        if not appt or appt.patient.telegram_chat_id != chat_id:
            return False, "Navbat topilmadi"
        try:
            cancel_appointment(db, appt)
        except BookingError as e:
            return False, e.detail
        return True, "Navbat bekor qilindi"


# --- navbat olish uchun ---
def _doctors() -> list[tuple[int, str]]:
    with SessionLocal() as db:
        ds = db.scalars(select(Doctor).options(selectinload(Doctor.user)).order_by(Doctor.id)).all()
        return [(d.id, f"{d.full_name} · {d.specialty}") for d in ds]


def _days(doctor_id: int) -> tuple[str, list[tuple[date, int]]] | None:
    """Shifokorning bo'sh vaqti bor kunlari va ulardagi bo'sh vaqtlar soni."""
    with SessionLocal() as db:
        doctor = db.get(Doctor, doctor_id)
        if not doctor:
            return None
        today = datetime.now(settings.tz).date()
        result = []
        for i in range(DAYS_AHEAD):
            day = today + timedelta(days=i)
            n = len(get_free_slots(db, doctor, day))
            if n:
                result.append((day, n))
        return doctor.full_name, result


def _slots(doctor_id: int, day: date) -> list[datetime]:
    with SessionLocal() as db:
        doctor = db.get(Doctor, doctor_id)
        if not doctor:
            return []
        return [start for start, _ in get_free_slots(db, doctor, day)]


def _book(chat_id: int, doctor_id: int, code: str) -> tuple[bool, str]:
    """code = YYYYMMDDHHMM (klinika vaqti). Sayt bilan bir xil xizmat: CRM'da ko'rinadi."""
    try:
        start = datetime.strptime(code, "%Y%m%d%H%M").replace(tzinfo=settings.tz)
    except ValueError:
        return False, "Vaqt noto'g'ri."
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            return False, "Avval /start bosib, ro'yxatdan o'ting."
        if user.role != Role.patient:
            return False, "Navbat olish faqat bemorlar uchun."
        doctor = db.get(Doctor, doctor_id)
        if not doctor:
            return False, "Shifokor topilmadi."
        try:
            appt = book_appointment(db, patient_id=user.id, doctor=doctor, start_at=start)
        except BookingError as e:
            return False, e.detail
        return True, "✅ Navbat band qilindi!\n" + format_appointment(appt)


# ---------- klaviaturalar ----------
def chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Shu yerda (botda) ro'yxatdan o'tish", callback_data="reg:bot")],
        [InlineKeyboardButton(text="🌐 Saytda ro'yxatdan o'tish", callback_data="reg:site")],
        [InlineKeyboardButton(text="✅ Allaqachon ro'yxatdan o'tganman", callback_data="reg:have")],
    ])


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Navbat olish", callback_data="bk:start")],
        [InlineKeyboardButton(text="🗓 Mening navbatlarim", callback_data="my")],
    ])


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


async def ask_choice(m: Message) -> None:
    await m.answer("Ro'yxatdan o'tishni qayerda davom ettirmoqchisiz?", reply_markup=choice_kb())


async def send_menu(m: Message) -> None:
    await m.answer("Nima qilamiz?", reply_markup=main_kb())


async def show(cq: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Xabarni joyida yangilaydi (chat to'lib ketmasligi uchun)."""
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        await cq.message.answer(text, reply_markup=kb)


# ---------- /start va tanlov ----------
@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    name = await asyncio.to_thread(_linked_name, m.chat.id)
    if name:
        await m.answer(f"Assalomu alaykum, {name}! Akkauntingiz ulangan.\n"
                       "Sayt uchun yangi parol: /parol", reply_markup=ReplyKeyboardRemove())
        await send_menu(m)
        return
    await m.answer("Assalomu alaykum! Qulay Davo botiga xush kelibsiz.", reply_markup=ReplyKeyboardRemove())
    await ask_choice(m)


@router.callback_query(F.data == "reg:bot")
async def reg_in_bot(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(Reg.name)
    await cq.message.answer("Ism-familiyangizni yozing (masalan: Aliyev Bobur).\n"
                            "Bekor qilish: /start")


@router.callback_query(F.data == "reg:site")
async def reg_on_site(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.clear()
    await cq.message.answer(
        f"Ro'yxatdan o'tish uchun saytga kiring:\n{SITE_URL}\n\n"
        "Ro'yxatdan o'tgach shu botga qaytib /start bosing va "
        "\"Allaqachon ro'yxatdan o'tganman\" tugmasini tanlang. "
        "Shunda eslatmalar Telegramga kela boshlaydi."
    )


@router.callback_query(F.data == "reg:have")
async def reg_have(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.clear()
    await cq.message.answer("Akkauntingizni ulash uchun saytda ro'yxatdan o'tgan telefon "
                            "raqamingizni ulashing.", reply_markup=contact_kb())


# ---------- botda ro'yxatdan o'tish: ism -> telefon -> parol ----------
@router.message(Reg.name, F.text, ~F.text.startswith("/"))
async def got_name(m: Message, state: FSMContext):
    name = " ".join(m.text.split())
    if not 2 <= len(name) <= 120:
        await m.answer("Ism-familiya 2 dan 120 belgigacha bo'lishi kerak. Qaytadan yozing:")
        return
    await state.update_data(name=name)
    await state.set_state(Reg.phone)
    await m.answer("Endi telefon raqamingizni ulashing (pastdagi tugmani bosing).",
                   reply_markup=contact_kb())


@router.message(Reg.phone, F.contact)
async def got_phone(m: Message, state: FSMContext):
    if m.contact.user_id != m.from_user.id:
        await m.answer("Iltimos, tugma orqali o'zingizning raqamingizni ulashing.")
        return
    try:
        phone = normalize_phone(m.contact.phone_number)
    except ValueError:
        await m.answer("Hozircha faqat O'zbekiston raqamlari (+998...) qabul qilinadi.")
        return
    # Raqam bilan akkaunt allaqachon bor bo'lsa, shuni ulaymiz (raqamni Telegram tasdiqlagan)
    existing = await asyncio.to_thread(_link_chat, phone, m.chat.id)
    if existing:
        await state.clear()
        await m.answer(f"Bu raqam bilan akkaunt bor edi, {existing}. U botga ulandi.",
                       reply_markup=ReplyKeyboardRemove())
        await send_menu(m)
        return
    await state.update_data(phone=phone)
    await state.set_state(Reg.password)
    await m.answer("Saytga kirish uchun parol o'ylab toping (kamida 6 belgi) va yozing. "
                   "Men uni xavfsizlik uchun chatdan o'chirib tashlayman.",
                   reply_markup=ReplyKeyboardRemove())


@router.message(Reg.phone, F.text, ~F.text.startswith("/"))
async def phone_need_button(m: Message):
    await m.answer("Raqamni yozmang, pastdagi \"Telefon raqamni ulashish\" tugmasini bosing. "
                   "Bekor qilish: /start")


@router.message(Reg.password, F.text, ~F.text.startswith("/"))
async def got_password(m: Message, state: FSMContext):
    password = m.text
    try:
        await m.delete()  # parol chatda qolmasin
    except Exception:
        pass
    if not 6 <= len(password) <= 72:
        await m.answer("Parol 6 dan 72 belgigacha bo'lishi kerak. Qaytadan yozing:")
        return
    data = await state.get_data()
    await state.clear()
    if not data.get("phone") or not data.get("name"):
        await m.answer("Xatolik yuz berdi. /start ni bosib qaytadan urinib ko'ring.")
        return
    ok = await asyncio.to_thread(_register, data["phone"], data["name"], password, m.chat.id)
    if not ok:
        await m.answer("Bu raqam allaqachon ro'yxatdan o'tgan. /start ni bosib akkauntni ulang.")
        return
    await m.answer(
        f"Ro'yxatdan o'tdingiz, {data['name']}! Endi navbatdan oldin eslatma yuboraman.\n\n"
        f"Saytga kirish: {SITE_URL}\nTelefon: +{data['phone']}\nParol: o'zingiz kiritgan parol."
    )
    await send_menu(m)


# ---------- mavjud akkauntni ulash (tanlov: "Allaqachon ro'yxatdan o'tganman") ----------
@router.message(F.contact)
async def got_contact(m: Message, state: FSMContext):
    contact = m.contact
    if contact.user_id != m.from_user.id:
        await m.answer("Iltimos, tugma orqali o'zingizning raqamingizni ulashing.")
        return
    try:
        phone = normalize_phone(contact.phone_number)
    except ValueError:
        await m.answer("Hozircha faqat O'zbekiston raqamlari (+998...) qabul qilinadi.")
        return
    name = await asyncio.to_thread(_link_chat, phone, m.chat.id)
    await state.clear()
    if name:
        await m.answer(f"Rahmat, {name}! Endi navbatingizdan oldin eslatma yuboraman.",
                       reply_markup=ReplyKeyboardRemove())
        await send_menu(m)
    else:
        await m.answer("Bu raqam bilan ro'yxatdan o'tilmagan.", reply_markup=ReplyKeyboardRemove())
        await ask_choice(m)


# ---------- navbat olish: shifokor -> kun -> vaqt ----------
async def doctors_screen(chat_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    role = await asyncio.to_thread(_role, chat_id)
    if role is None:
        return "Avval /start bosib, ro'yxatdan o'ting yoki akkauntingizni ulang.", None
    if role != Role.patient:
        return "Navbat olish faqat bemorlar uchun.", None
    items = await asyncio.to_thread(_doctors)
    if not items:
        return "Hozircha shifokorlar yo'q.", None
    rows = [[InlineKeyboardButton(text=t, callback_data=f"bk:d:{i}")] for i, t in items]
    return "Shifokorni tanlang:", InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("navbat"))
async def cmd_navbat(m: Message):
    text, kb = await doctors_screen(m.chat.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "bk:start")
async def bk_start(cq: CallbackQuery):
    await cq.answer()
    text, kb = await doctors_screen(cq.from_user.id)
    await show(cq, text, kb)


@router.callback_query(F.data.startswith("bk:d:"))
async def bk_doctor(cq: CallbackQuery):
    await cq.answer()
    doctor_id = int(cq.data.split(":")[2])
    res = await asyncio.to_thread(_days, doctor_id)
    back = [InlineKeyboardButton(text="⬅️ Shifokorlar", callback_data="bk:start")]
    if res is None:
        await show(cq, "Shifokor topilmadi.", InlineKeyboardMarkup(inline_keyboard=[back]))
        return
    name, days = res
    if not days:
        await show(cq, f"{name}: yaqin kunlarda bo'sh vaqt yo'q.",
                   InlineKeyboardMarkup(inline_keyboard=[back]))
        return
    btns = [InlineKeyboardButton(text=f"{d:%d.%m} {WD[d.weekday()]} ({n})",
                                 callback_data=f"bk:t:{doctor_id}:{d:%Y%m%d}") for d, n in days]
    await show(cq, f"{name}\nKunni tanlang (qavsda bo'sh vaqtlar soni):",
               InlineKeyboardMarkup(inline_keyboard=chunk(btns, 2) + [back]))


async def slots_screen(cq: CallbackQuery, doctor_id: int, day_code: str) -> None:
    day = datetime.strptime(day_code, "%Y%m%d").date()
    slots = await asyncio.to_thread(_slots, doctor_id, day)
    back = [InlineKeyboardButton(text="⬅️ Kunlar", callback_data=f"bk:d:{doctor_id}")]
    if not slots:
        await show(cq, "Bu kunda bo'sh vaqt qolmadi.", InlineKeyboardMarkup(inline_keyboard=[back]))
        return
    btns = [InlineKeyboardButton(text=f"{s:%H:%M}", callback_data=f"bk:s:{doctor_id}:{s:%Y%m%d%H%M}")
            for s in slots]
    await show(cq, f"{day:%d.%m.%Y} ({WD[day.weekday()]}). Vaqtni tanlang:",
               InlineKeyboardMarkup(inline_keyboard=chunk(btns, 4) + [back]))


@router.callback_query(F.data.startswith("bk:t:"))
async def bk_day(cq: CallbackQuery):
    await cq.answer()
    _, _, doctor_id, day_code = cq.data.split(":")
    await slots_screen(cq, int(doctor_id), day_code)


@router.callback_query(F.data.startswith("bk:s:"))
async def bk_slot(cq: CallbackQuery):
    _, _, doctor_id, code = cq.data.split(":")
    ok, text = await asyncio.to_thread(_book, cq.from_user.id, int(doctor_id), code)
    if ok:
        await cq.answer("Navbat band qilindi ✅")
        await show(cq, text, main_kb())
    else:
        await cq.answer(text, show_alert=True)  # masalan, vaqtni boshqa bemor band qilgan
        await slots_screen(cq, int(doctor_id), code[:8])


# ---------- navbatlar, parol ----------
async def send_my(msg: Message, chat_id: int) -> None:
    items = await asyncio.to_thread(_upcoming, chat_id)
    if items is None:
        await msg.answer("Avval /start bosib, ro'yxatdan o'ting yoki akkauntingizni ulang.")
        return
    if not items:
        await msg.answer("Kelgusi navbatlaringiz yo'q. Navbat olish: /navbat")
        return
    for appt_id, text in items:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"cancel:{appt_id}")
        ]])
        await msg.answer(text, reply_markup=kb)


@router.message(Command("my"))
async def my_appointments(m: Message):
    await send_my(m, m.chat.id)


@router.callback_query(F.data == "my")
async def my_cb(cq: CallbackQuery):
    await cq.answer()
    await send_my(cq.message, cq.from_user.id)


@router.message(Command("parol"))
async def new_password(m: Message):
    temp = await asyncio.to_thread(_reset_password, m.chat.id)
    if temp is None:
        await m.answer("Bu buyruq faqat botga ulangan bemor akkauntlari uchun ishlaydi. "
                       "Avval /start bosing.")
        return
    await m.answer(f"Saytga kirish uchun yangi parol: {temp}\n"
                   "Xavfsizlik uchun bu xabarni o'qib bo'lgach o'chirib tashlang.")


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_cb(cq: CallbackQuery):
    appt_id = int(cq.data.split(":")[1])
    ok, msg = await asyncio.to_thread(_cancel, appt_id, cq.from_user.id)
    await cq.answer(msg, show_alert=True)
    if ok and cq.message:
        await cq.message.edit_text(f"{cq.message.text}\n\n❌ Bekor qilindi")


async def main():
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN .env faylida ko'rsatilmagan")
    logging.basicConfig(level=logging.INFO)
    bot = Bot(settings.telegram_bot_token)
    await bot.set_my_commands([
        BotCommand(command="navbat", description="Navbat olish"),
        BotCommand(command="my", description="Mening navbatlarim"),
        BotCommand(command="parol", description="Sayt uchun yangi parol"),
        BotCommand(command="start", description="Boshidan boshlash"),
    ])
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
