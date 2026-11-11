import re
import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update

from app.api.deps import DB, AdminUser, require_roles
from app.core.security import hash_password
from app.models import (
    Appointment, AppointmentStatus, Notification, NotificationStatus, Role, User,
)
from app.schemas import Phone, UserOut

router = APIRouter(tags=["CRM"])

FrontDesk = Annotated[User, Depends(require_roles(Role.admin, Role.receptionist))]
AnyStaff = Annotated[User, Depends(require_roles(Role.admin, Role.receptionist, Role.doctor))]


class PatientCreate(BaseModel):
    phone: Phone
    full_name: str = Field(min_length=2, max_length=120)


class StaffCreate(BaseModel):
    phone: Phone
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=72)
    role: Literal["receptionist", "admin"] = "receptionist"


class StatusIn(BaseModel):
    status: AppointmentStatus


@router.get("/patients", response_model=list[UserOut])
def list_patients(db: DB, _: FrontDesk, q: str = "", limit: int = Query(50, ge=1, le=200),
                  offset: int = Query(0, ge=0)):
    """Bemorlar ro'yxati. q - ism yoki telefon bo'yicha qidiruv."""
    stmt = select(User).where(User.role == Role.patient)
    q = q.strip()
    if q:
        digits = re.sub(r"\D", "", q)
        conds = [User.full_name.ilike(f"%{q}%")]
        if digits:
            conds.append(User.phone.contains(digits))
        stmt = stmt.where(or_(*conds))
    return db.scalars(stmt.order_by(User.full_name).limit(limit).offset(offset)).all()


@router.post("/patients", status_code=201)
def create_patient(data: PatientCreate, db: DB, _: FrontDesk):
    """Registratura bemorni o'zi ro'yxatga oladi. Vaqtinchalik parol qaytariladi."""
    if db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(409, "Bu raqam allaqachon ro'yxatdan o'tgan")
    temp = secrets.token_urlsafe(6)
    user = User(phone=data.phone, full_name=data.full_name,
                password_hash=hash_password(temp), role=Role.patient)
    db.add(user)
    db.commit()
    return {"id": user.id, "phone": user.phone, "full_name": user.full_name, "temp_password": temp}


@router.post("/staff", status_code=201)
def create_staff(data: StaffCreate, db: DB, _: AdminUser):
    """Registrator yoki yangi admin yaratish (faqat admin)."""
    if db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(409, "Bu raqam allaqachon ro'yxatdan o'tgan")
    user = User(phone=data.phone, full_name=data.full_name,
                password_hash=hash_password(data.password), role=Role(data.role))
    db.add(user)
    db.commit()
    return {"id": user.id, "phone": user.phone, "role": user.role.value}


@router.patch("/appointments/{appt_id}/status")
def set_status(appt_id: int, data: StatusIn, db: DB, user: AnyStaff):
    """Navbatni 'done' (keldi) yoki 'no_show' (kelmadi) deb belgilash."""
    if data.status not in (AppointmentStatus.done, AppointmentStatus.no_show):
        raise HTTPException(422, "Faqat done yoki no_show ruxsat etiladi (bekor qilish uchun /cancel)")
    appt = db.get(Appointment, appt_id)
    if not appt:
        raise HTTPException(404, "Navbat topilmadi")
    if user.role == Role.doctor and appt.doctor.user_id != user.id:
        raise HTTPException(403, "Bu navbat sizga tegishli emas")
    if appt.status != AppointmentStatus.booked:
        raise HTTPException(409, "Faqat faol navbatning holatini o'zgartirish mumkin")
    appt.status = data.status
    db.execute(update(Notification)
               .where(Notification.appointment_id == appt.id,
                      Notification.status == NotificationStatus.pending)
               .values(status=NotificationStatus.cancelled))
    db.commit()
    return {"id": appt.id, "status": appt.status.value}
