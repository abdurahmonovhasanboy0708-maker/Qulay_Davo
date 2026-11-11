import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, require_roles
from app.core.config import settings
from app.models import Appointment, AppointmentStatus, Doctor, Role, User
from app.schemas import AppointmentCreate, AppointmentOut, AppointmentReschedule
from app.services import appointments as svc

router = APIRouter(prefix="/appointments", tags=["Appointments"])

_LOAD = (
    selectinload(Appointment.patient),
    selectinload(Appointment.doctor).selectinload(Doctor.user),
    selectinload(Appointment.doctor).selectinload(Doctor.cabinet),
)


def _get_or_404(db, appt_id: int) -> Appointment:
    appt = db.scalar(select(Appointment).options(*_LOAD).where(Appointment.id == appt_id))
    if not appt:
        raise HTTPException(404, "Navbat topilmadi")
    return appt


def _ensure_can_manage(user: User, appt: Appointment) -> None:
    if user.role in (Role.admin, Role.receptionist):
        return
    if user.role == Role.patient and appt.patient_id == user.id:
        return
    if user.role == Role.doctor and appt.doctor.user_id == user.id:
        return
    raise HTTPException(403, "Bu navbat sizga tegishli emas")


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.BookingError as e:
        raise HTTPException(e.status_code, e.detail)


@router.post("", response_model=AppointmentOut, status_code=201)
def create_appointment(
    data: AppointmentCreate, db: DB,
    user: User = Depends(require_roles(Role.patient, Role.admin, Role.receptionist)),
):
    """Bemor o'zi uchun navbat oladi. Admin/registrator esa patient_id ni ko'rsatadi."""
    if user.role == Role.patient:
        patient_id = user.id
    else:
        if not data.patient_id:
            raise HTTPException(422, "patient_id ko'rsatilishi kerak")
        patient = db.get(User, data.patient_id)
        if not patient or patient.role != Role.patient:
            raise HTTPException(404, "Bemor topilmadi")
        patient_id = patient.id
    doctor = db.get(Doctor, data.doctor_id)
    if not doctor:
        raise HTTPException(404, "Shifokor topilmadi")
    appt = _run(svc.book, db, patient_id=patient_id, doctor=doctor,
                start_at=data.start_at, note=data.note)
    return _get_or_404(db, appt.id)


@router.get("/my", response_model=list[AppointmentOut])
def my_appointments(db: DB, user: CurrentUser, upcoming_only: bool = False):
    q = select(Appointment).options(*_LOAD).where(Appointment.patient_id == user.id)
    if upcoming_only:
        q = q.where(Appointment.status == AppointmentStatus.booked,
                    Appointment.start_at > dt.datetime.now(dt.timezone.utc))
    return db.scalars(q.order_by(Appointment.start_at.desc())).all()


@router.get("", response_model=list[AppointmentOut])
def list_appointments(
    db: DB,
    user: User = Depends(require_roles(Role.admin, Role.receptionist, Role.doctor)),
    doctor_id: int | None = None,
    status: AppointmentStatus | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Xodimlar uchun ro'yxat. Shifokor faqat o'z navbatlarini ko'radi."""
    q = select(Appointment).options(*_LOAD)
    if user.role == Role.doctor:
        doctor_id = user.doctor.id
    if doctor_id:
        q = q.where(Appointment.doctor_id == doctor_id)
    if status:
        q = q.where(Appointment.status == status)
    tz = settings.tz
    if date_from:
        q = q.where(Appointment.start_at >= dt.datetime.combine(date_from, dt.time.min, tzinfo=tz))
    if date_to:
        q = q.where(Appointment.start_at < dt.datetime.combine(date_to, dt.time.min, tzinfo=tz)
                    + dt.timedelta(days=1))
    return db.scalars(q.order_by(Appointment.start_at).limit(limit).offset(offset)).all()


@router.patch("/{appt_id}/cancel", response_model=AppointmentOut)
def cancel(appt_id: int, db: DB, user: CurrentUser):
    appt = _get_or_404(db, appt_id)
    _ensure_can_manage(user, appt)
    _run(svc.cancel_appointment, db, appt)
    return appt


@router.patch("/{appt_id}/reschedule", response_model=AppointmentOut)
def reschedule(appt_id: int, data: AppointmentReschedule, db: DB, user: CurrentUser):
    appt = _get_or_404(db, appt_id)
    _ensure_can_manage(user, appt)
    _run(svc.reschedule, db, appt, data.start_at)
    return _get_or_404(db, appt_id)
