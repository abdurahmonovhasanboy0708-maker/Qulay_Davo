import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser
from app.core.config import settings
from app.models import Appointment, Doctor, User

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/appointments")
def appointments_report(
    db: DB, _: AdminUser,
    date_from: Annotated[dt.date, Query(alias="from")],
    date_to: Annotated[dt.date, Query(alias="to")],
):
    """Davr bo'yicha navbatlar statistikasi: statuslar va shifokorlar kesimida."""
    tz = settings.tz
    start = dt.datetime.combine(date_from, dt.time.min, tzinfo=tz)
    end = dt.datetime.combine(date_to, dt.time.min, tzinfo=tz) + dt.timedelta(days=1)
    in_range = (Appointment.start_at >= start, Appointment.start_at < end)

    by_status = db.execute(
        select(Appointment.status, func.count()).where(*in_range).group_by(Appointment.status)
    ).all()
    by_doctor = db.execute(
        select(Doctor.id, User.full_name, func.count(Appointment.id))
        .join(Appointment, Appointment.doctor_id == Doctor.id)
        .join(User, User.id == Doctor.user_id)
        .where(*in_range)
        .group_by(Doctor.id, User.full_name)
        .order_by(func.count(Appointment.id).desc())
    ).all()
    return {
        "from": date_from, "to": date_to,
        "total": sum(c for _, c in by_status),
        "by_status": {s.value: c for s, c in by_status},
        "by_doctor": [{"doctor_id": i, "doctor": n, "appointments": c} for i, n, c in by_doctor],
    }
