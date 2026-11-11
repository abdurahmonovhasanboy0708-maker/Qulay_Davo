"""Bo'sh vaqtlarni (slotlarni) hisoblash."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Appointment, AppointmentStatus, Doctor


def compute_slots(
    day: date,
    windows: list[tuple[time, time]],
    slot_minutes: int,
    busy: list[tuple[datetime, datetime]],
    now: datetime,
    tz: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    """Sof funksiya (DB siz) - shuning uchun oson test qilinadi.

    windows - shu kundagi ish oraliqlari, busy - band qilingan oraliqlar,
    now - hozirgi vaqt (o'tib ketgan slotlar chiqmaydi).
    """
    step = timedelta(minutes=slot_minutes)
    result: list[tuple[datetime, datetime]] = []
    for start_t, end_t in sorted(windows):
        cur = datetime.combine(day, start_t, tzinfo=tz)
        end = datetime.combine(day, end_t, tzinfo=tz)
        while cur + step <= end:
            nxt = cur + step
            overlaps = any(cur < b_end and nxt > b_start for b_start, b_end in busy)
            if cur > now and not overlaps:
                result.append((cur, nxt))
            cur = nxt
    return result


def get_free_slots(db: Session, doctor: Doctor, day: date) -> list[tuple[datetime, datetime]]:
    tz = settings.tz
    windows = [(s.start_time, s.end_time) for s in doctor.schedules if s.weekday == day.weekday()]
    if not windows:
        return []
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    rows = db.execute(
        select(Appointment.start_at, Appointment.end_at).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.booked,
            Appointment.start_at < day_end,
            Appointment.end_at > day_start,
        )
    ).all()
    busy = [(r.start_at, r.end_at) for r in rows]
    return compute_slots(day, windows, doctor.slot_minutes, busy, datetime.now(tz), tz)
