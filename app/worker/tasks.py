import logging
from collections import Counter
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    Appointment, AppointmentStatus, Channel, Doctor, Notification, NotificationStatus, User,
)
from app.services.messages import queue_text, reminder_text
from app.services.sms import send_sms
from app.services.telegram import send_telegram
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
BATCH = 50

# Soatlik "navbat holati" xabarlari: faqat shu mahalliy soatlar oralig'ida (tunda yuborilmaydi)
QUEUE_FROM_HOUR, QUEUE_TO_HOUR = 8, 20
# Navbatga shuncha daqiqadan kam qolsa, soatlik xabar yuborilmaydi (60/30 daqiqalik eslatmalar bor)
QUEUE_MIN_LEAD = timedelta(minutes=45)


class _Skip(Exception):
    pass


@celery_app.task(name="app.worker.tasks.dispatch_due_notifications")
def dispatch_due_notifications() -> dict:
    """Vaqti kelgan (send_at <= hozir) va hali yuborilmagan eslatmalarni yuboradi.

    FOR UPDATE SKIP LOCKED - bir nechta ishchi parallel ishlasa ham,
    bir xil xabar ikki marta ketmaydi.
    """
    now = datetime.now(timezone.utc)
    stats: Counter = Counter()
    with SessionLocal() as db:
        due = db.scalars(
            select(Notification)
            .where(Notification.status == NotificationStatus.pending,
                   Notification.send_at <= now)
            .order_by(Notification.send_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        ).all()

        for n in due:
            appt = n.appointment
            if appt.status != AppointmentStatus.booked:
                n.status = NotificationStatus.cancelled
                stats["cancelled"] += 1
                continue
            if appt.start_at <= now:  # navbat vaqti o'tib ketgan, eslatma kerak emas
                n.status = NotificationStatus.skipped
                n.error = "Navbat vaqti o'tib ketgan"
                stats["skipped"] += 1
                continue
            try:
                _deliver(n)
                n.status = NotificationStatus.sent
                n.sent_at = now
                stats["sent"] += 1
            except _Skip as e:
                n.status = NotificationStatus.skipped
                n.error = str(e)
                stats["skipped"] += 1
            except Exception as e:  # tarmoq xatosi va h.k. - keyingi daqiqada qayta urinamiz
                n.attempts += 1
                n.error = str(e)[:500]
                if n.attempts >= MAX_ATTEMPTS:
                    n.status = NotificationStatus.failed
                    stats["failed"] += 1
                else:
                    stats["retry"] += 1
                logger.warning("Notification %s xato: %s", n.id, e)
        db.commit()
    return dict(stats)


def _deliver(n: Notification) -> None:
    appt = n.appointment
    text = reminder_text(appt, n.kind)
    if n.channel == Channel.sms:
        send_sms(appt.patient.phone, text)
    elif n.channel == Channel.telegram:
        chat_id = appt.patient.telegram_chat_id
        if not chat_id:
            raise _Skip("Bemor Telegram botni ulamagan")
        send_telegram(chat_id, text)


@celery_app.task(name="app.worker.tasks.send_queue_updates")
def send_queue_updates() -> dict:
    """Har soatda: bugungi navbati bor va Telegramni ulagan bemorlarga
    'sizdan oldin nechta kishi bor' va taxminiy vaqtni yuboradi."""
    tz = settings.tz
    now = datetime.now(timezone.utc)
    local = now.astimezone(tz)
    if not QUEUE_FROM_HOUR <= local.hour <= QUEUE_TO_HOUR:
        return {"skipped": "tungi vaqt"}

    day_end = datetime.combine(local.date(), time.min, tzinfo=tz) + timedelta(days=1)
    stats: Counter = Counter()
    with SessionLocal() as db:
        appts = db.scalars(
            select(Appointment)
            .join(User, User.id == Appointment.patient_id)
            .options(
                selectinload(Appointment.patient),
                selectinload(Appointment.doctor).selectinload(Doctor.user),
                selectinload(Appointment.doctor).selectinload(Doctor.cabinet),
            )
            .where(Appointment.status == AppointmentStatus.booked,
                   Appointment.start_at > now + QUEUE_MIN_LEAD,
                   Appointment.start_at < day_end,
                   User.telegram_chat_id.is_not(None))
            .order_by(Appointment.start_at)
        ).all()

        for a in appts:
            # Oldingi navbatlar: shu shifokorning, hali "Keldi/Kelmadi/Bekor" qilinmagan
            # va vaqti hali tugamagan navbatlari
            ahead = db.scalar(
                select(func.count()).select_from(Appointment).where(
                    Appointment.doctor_id == a.doctor_id,
                    Appointment.status == AppointmentStatus.booked,
                    Appointment.start_at < a.start_at,
                    Appointment.end_at > now,
                )
            )
            try:
                send_telegram(a.patient.telegram_chat_id, queue_text(a, ahead))
                stats["sent"] += 1
            except Exception as e:
                stats["failed"] += 1
                logger.warning("Queue update (appt %s) xato: %s", a.id, e)
    return dict(stats)
