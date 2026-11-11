"""Navbat yaratish / bekor qilish / ko'chirish + ogohlantirishlarni rejalashtirish."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Appointment, AppointmentStatus, Channel, Doctor, Notification, NotificationStatus,
)
from app.services.slots import get_free_slots

# Navbatga necha daqiqa qolganda eslatma yuboriladi
REMINDER_OFFSETS = (60, 30)


class BookingError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=settings.tz)


def _slot_is_free(db: Session, doctor: Doctor, start_at: datetime) -> bool:
    free = get_free_slots(db, doctor, start_at.astimezone(settings.tz).date())
    return any(s == start_at for s, _ in free)


def create_notifications(db: Session, appt: Appointment) -> None:
    """Har bir eslatma uchun har bir kanalga (SMS, Telegram) alohida yozuv."""
    now = datetime.now(timezone.utc)
    for minutes in REMINDER_OFFSETS:
        send_at = appt.start_at - timedelta(minutes=minutes)
        if send_at <= now:
            continue  # navbat juda yaqin - bu eslatma ma'nosiz
        for channel in Channel:
            db.add(
                Notification(
                    appointment_id=appt.id, channel=channel,
                    kind=f"before_{minutes}", send_at=send_at,
                )
            )


def book(db: Session, *, patient_id: int, doctor: Doctor, start_at: datetime,
         note: str | None = None) -> Appointment:
    start_at = _aware(start_at)
    if not _slot_is_free(db, doctor, start_at):
        raise BookingError(409, "Bu vaqt band, ish vaqtidan tashqarida yoki o'tib ketgan")

    appt = Appointment(
        patient_id=patient_id, doctor_id=doctor.id, start_at=start_at,
        end_at=start_at + timedelta(minutes=doctor.slot_minutes),
        status=AppointmentStatus.booked, note=note,
    )
    db.add(appt)
    try:
        # Ikki kishi bir vaqtda band qilsa, EXCLUDE constraint ikkinchisini rad etadi
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BookingError(409, "Bu vaqtni hozirgina boshqa bemor band qildi")
    create_notifications(db, appt)
    db.commit()
    return appt


def cancel_appointment(db: Session, appt: Appointment) -> Appointment:
    if appt.status != AppointmentStatus.booked:
        raise BookingError(409, "Faqat faol navbatni bekor qilish mumkin")
    appt.status = AppointmentStatus.cancelled
    db.execute(
        update(Notification)
        .where(Notification.appointment_id == appt.id,
               Notification.status == NotificationStatus.pending)
        .values(status=NotificationStatus.cancelled)
    )
    db.commit()
    return appt


def reschedule(db: Session, appt: Appointment, new_start: datetime) -> Appointment:
    if appt.status != AppointmentStatus.booked:
        raise BookingError(409, "Faqat faol navbatni ko'chirish mumkin")
    new_start = _aware(new_start)
    if new_start == appt.start_at:
        return appt
    if not _slot_is_free(db, appt.doctor, new_start):
        raise BookingError(409, "Tanlangan vaqt band, ish vaqtidan tashqarida yoki o'tib ketgan")

    appt.start_at = new_start
    appt.end_at = new_start + timedelta(minutes=appt.doctor.slot_minutes)
    # eski (hali yuborilmagan) eslatmalarni o'chirib, yangilarini yaratamiz
    db.execute(
        delete(Notification).where(
            Notification.appointment_id == appt.id,
            Notification.status == NotificationStatus.pending,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BookingError(409, "Bu vaqtni hozirgina boshqa bemor band qildi")
    create_notifications(db, appt)
    db.commit()
    return appt
