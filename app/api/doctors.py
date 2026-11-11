import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, AdminUser
from app.core.security import hash_password
from app.models import Cabinet, Doctor, Role, User, WorkSchedule
from app.schemas import (
    DoctorCreate, DoctorOut, ScheduleIn, ScheduleItem, SlotOut, SlotsOut,
)
from app.services.slots import get_free_slots

router = APIRouter(prefix="/doctors", tags=["Doctors"])


def _doctor_or_404(db, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(404, "Shifokor topilmadi")
    return doctor


@router.get("", response_model=list[DoctorOut])
def list_doctors(
    db: DB,
    specialty: str | None = Query(None, description="Mutaxassislik bo'yicha qidirish"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    q = select(Doctor).options(selectinload(Doctor.user), selectinload(Doctor.cabinet))
    if specialty:
        q = q.where(Doctor.specialty.ilike(f"%{specialty}%"))
    return db.scalars(q.order_by(Doctor.id).limit(limit).offset(offset)).all()


@router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: int, db: DB):
    return _doctor_or_404(db, doctor_id)


@router.get("/{doctor_id}/slots", response_model=SlotsOut)
def get_slots(doctor_id: int, db: DB, day: Annotated[dt.date, Query(alias="date")]):
    """Berilgan kundagi bo'sh vaqtlar."""
    doctor = _doctor_or_404(db, doctor_id)
    slots = get_free_slots(db, doctor, day)
    return SlotsOut(doctor_id=doctor.id, day=day,
                    slots=[SlotOut(start_at=s, end_at=e) for s, e in slots])


@router.get("/{doctor_id}/schedule", response_model=list[ScheduleItem])
def get_schedule(doctor_id: int, db: DB):
    doctor = _doctor_or_404(db, doctor_id)
    return sorted(doctor.schedules, key=lambda s: (s.weekday, s.start_time))


@router.post("", response_model=DoctorOut, status_code=201)
def create_doctor(data: DoctorCreate, db: DB, _: AdminUser):
    if db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(409, "Bu raqam allaqachon ro'yxatdan o'tgan")
    if data.cabinet_id and not db.get(Cabinet, data.cabinet_id):
        raise HTTPException(404, "Kabinet topilmadi")
    user = User(phone=data.phone, full_name=data.full_name,
                password_hash=hash_password(data.password), role=Role.doctor)
    db.add(user)
    db.flush()
    doctor = Doctor(user_id=user.id, specialty=data.specialty,
                    cabinet_id=data.cabinet_id, slot_minutes=data.slot_minutes)
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.put("/{doctor_id}/schedule", response_model=list[ScheduleItem])
def set_schedule(doctor_id: int, data: ScheduleIn, db: DB, _: AdminUser):
    """Haftalik ish jadvalini to'liq almashtiradi."""
    _doctor_or_404(db, doctor_id)
    by_day: dict[int, list[ScheduleItem]] = {}
    for item in data.items:
        by_day.setdefault(item.weekday, []).append(item)
    for items in by_day.values():
        items.sort(key=lambda i: i.start_time)
        for a, b in zip(items, items[1:]):
            if b.start_time < a.end_time:
                raise HTTPException(422, "Bir kundagi ish oraliqlari kesishmasligi kerak")
    db.execute(delete(WorkSchedule).where(WorkSchedule.doctor_id == doctor_id))
    for item in data.items:
        db.add(WorkSchedule(doctor_id=doctor_id, weekday=item.weekday,
                            start_time=item.start_time, end_time=item.end_time))
    db.commit()
    return sorted(data.items, key=lambda s: (s.weekday, s.start_time))
