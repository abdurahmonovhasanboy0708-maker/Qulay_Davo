# Qulay Davo API

Klinika uchun **navbat band qilish tizimi**: shifokorlar va ish jadvali, bo'sh vaqtlar, navbat olish,
navbatdan **1 soat va 30 daqiqa oldin SMS + Telegram eslatma** hamda **shifokor kabineti asboblari inventari**.

**Stack:** Python, FastAPI, PostgreSQL, SQLAlchemy 2 + Alembic, Celery + Redis, aiogram 3, Docker.

## Ishga tushirish (Docker, eng oson)

```bash
cp .env.example .env
docker compose up --build            # api, worker, beat, bot, postgres, redis
docker compose exec api python -m app.scripts.seed   # demo ma'lumotlar
```
Swagger: http://localhost:8000/docs

Demo loginlar (seeddan keyin): admin `998900000001 / admin123`, shifokor `998900000002 / doctor123`,
bemor `998900000003 / patient123`.

## PyCharm'da lokal ishga tushirish

```bash
docker compose up -d db redis              # faqat baza va redis
pip install -r requirements.txt
alembic upgrade head
python -m app.scripts.seed
uvicorn app.main:app --reload              # API
celery -A app.worker.celery_app.celery_app worker -B -l info   # eslatmalar (worker + beat)
python -m app.bot.main                     # Telegram bot (TELEGRAM_BOT_TOKEN kerak)
pytest
```
`requests.http` faylini PyCharm'da ochib, so'rovlarni to'g'ridan-to'g'ri yuborishingiz mumkin.

## Arxitektura va muhim qarorlar

- **Navbat to'qnashuvi bazada hal qilinadi.** `appointments` jadvalida PostgreSQL `EXCLUDE USING gist`
  constraint bor: bir shifokorning faol (`booked`) navbatlari vaqt bo'yicha kesisha olmaydi.
  Ikki bemor bir vaqtda bosganda ham faqat bittasi o'tadi, ikkinchisi `409` oladi.
- **Eslatmalar.** Navbat yaratilganda `notifications` jadvaliga har bir (60/30 daqiqa) x (SMS/Telegram)
  uchun yozuv qo'shiladi. Celery beat har daqiqada `dispatch_due_notifications` ni ishga tushiradi:
  vaqti kelganlarni `FOR UPDATE SKIP LOCKED` bilan oladi (bir xabar ikki marta ketmaydi),
  xato bo'lsa 3 martagacha qayta urinadi, so'ng `failed`. Navbat bekor qilinsa/ko'chirilsa,
  eski eslatmalar bekor qilinib, yangilari yaratiladi.
- **SMS** - Eskiz.uz. `ESKIZ_EMAIL` bo'sh bo'lsa, SMS faqat logga yoziladi (dry-run).
  Telegram ham xuddi shunday (`TELEGRAM_BOT_TOKEN` bo'sh bo'lsa dry-run).
- **Telegram bot.** `/start` -> telefon raqamni ulashish tugmasi -> bot raqamni saytdagi foydalanuvchi bilan
  moslab `telegram_chat_id` ni saqlaydi. `/my` - kelgusi navbatlar va "Bekor qilish" tugmasi.
- **Inventar.** Katalog (`instruments`) + kabinetdagi holat (`cabinet_instruments`: soni, minimum, holati)
  + audit (`instrument_logs`: kim, qachon, nimani o'zgartirdi).
  `GET /cabinets/{id}/instruments/overview` - bor / kam qolgan / buzuq / umuman yo'q asboblarni bitta javobda beradi.
- **Rollar:** bemor (o'z navbatlari), shifokor (o'z navbatlari va o'z kabineti), registrator (navbatlar, inventarni ko'rish), admin (hamma narsa).

## Asosiy endpointlar

| Metod | Yo'l | Kim |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, GET `/auth/me` | hamma |
| GET | `/doctors?specialty=`, `/doctors/{id}/slots?date=YYYY-MM-DD` | hamma |
| POST | `/doctors`, PUT `/doctors/{id}/schedule`, POST `/cabinets` | admin |
| POST | `/appointments` | bemor / registrator / admin |
| GET | `/appointments/my`, `/appointments` (xodimlar) | |
| PATCH | `/appointments/{id}/cancel`, `/appointments/{id}/reschedule` | egasi yoki xodim |
| GET/POST/PATCH | `/cabinets/{id}/instruments[...]`, `/instruments` | shifokor (o'z kabineti) / admin |
| GET | `/cabinets/{id}/instruments/overview`, `/low-stock`, `/logs` | |
| GET | `/reports/appointments?from=&to=` | admin |

## Keyingi qadamlar (portfolio uchun)

- PostgreSQL bilan integration testlar (testcontainers yoki CI'da postgres service)
- Rate limiting va strukturalangan loglar, Redis cache (slotlar)
- Payme/Click sandbox to'lov integratsiyasi
- Deploy (Render / Railway / Fly.io) va jonli havola README'ga
- Oddiy frontend (React/Next.js) yoki Telegram Mini App

## Eslatma

`alembic/versions/0001_initial.py` - boshlang'ich (baseline) migratsiya: u jadvallarni yaratadi va
EXCLUDE constraintni qo'shadi. Keyingi o'zgarishlarni `alembic revision --autogenerate -m "..."` bilan qiling.
