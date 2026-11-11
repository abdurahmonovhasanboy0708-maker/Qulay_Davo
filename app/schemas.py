import re
from datetime import date, datetime, time
from typing import Annotated

from pydantic import (
    AfterValidator, BaseModel, ConfigDict, Field, computed_field, model_validator,
)

from app.models import AppointmentStatus, InstrumentStatus, Role


def normalize_phone(raw: str) -> str:
    """'+998 90 123-45-67' / '901234567' -> '998901234567'"""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        digits = "998" + digits
    if not (len(digits) == 12 and digits.startswith("998")):
        raise ValueError("Telefon raqam noto'g'ri. Masalan: +998901234567")
    return digits


Phone = Annotated[str, AfterValidator(normalize_phone)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth / users ----------
class RegisterIn(BaseModel):
    phone: Phone
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: int
    phone: str
    full_name: str
    role: Role
    telegram_chat_id: int | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def telegram_linked(self) -> bool:
        return self.telegram_chat_id is not None


# ---------- Cabinets / doctors ----------
class CabinetIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    floor: int = 1


class CabinetOut(ORM):
    id: int
    name: str
    floor: int


class DoctorCreate(BaseModel):
    phone: Phone
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=72)
    specialty: str = Field(min_length=2, max_length=100)
    cabinet_id: int | None = None
    slot_minutes: int = Field(default=30, ge=5, le=120)


class DoctorOut(ORM):
    id: int
    full_name: str
    specialty: str
    cabinet_id: int | None
    cabinet_name: str | None
    slot_minutes: int


class ScheduleItem(ORM):
    weekday: int = Field(ge=0, le=6, description="0=Dushanba ... 6=Yakshanba")
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _check(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time start_time dan keyin bo'lishi kerak")
        return self


class ScheduleIn(BaseModel):
    items: list[ScheduleItem]


class SlotOut(BaseModel):
    start_at: datetime
    end_at: datetime


class SlotsOut(BaseModel):
    doctor_id: int
    day: date
    slots: list[SlotOut]


# ---------- Appointments ----------
class AppointmentCreate(BaseModel):
    doctor_id: int
    start_at: datetime = Field(description="Slot boshlanish vaqti, masalan 2026-11-05T10:30:00+05:00")
    patient_id: int | None = Field(default=None, description="Faqat admin/registrator uchun")
    note: str | None = Field(default=None, max_length=500)


class AppointmentReschedule(BaseModel):
    start_at: datetime


class AppointmentOut(ORM):
    id: int
    patient_id: int
    patient_name: str
    doctor_id: int
    doctor_name: str
    specialty: str
    cabinet_name: str | None
    start_at: datetime
    end_at: datetime
    status: AppointmentStatus
    note: str | None


# ---------- Inventory ----------
class InstrumentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str | None = Field(default=None, max_length=60)


class InstrumentOut(ORM):
    id: int
    name: str
    category: str | None


class CabinetItemCreate(BaseModel):
    instrument_id: int | None = None
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = None
    quantity: int = Field(default=1, ge=0)
    min_quantity: int = Field(default=1, ge=0)
    status: InstrumentStatus = InstrumentStatus.available

    @model_validator(mode="after")
    def _need_id_or_name(self):
        if self.instrument_id is None and not self.name:
            raise ValueError("instrument_id yoki name berilishi kerak")
        return self


class CabinetItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=0)
    min_quantity: int | None = Field(default=None, ge=0)
    status: InstrumentStatus | None = None
    reason: str | None = Field(default=None, max_length=255)


class CabinetItemOut(ORM):
    id: int
    instrument_id: int
    name: str
    category: str | None
    quantity: int
    min_quantity: int
    status: InstrumentStatus
    is_low: bool


class InstrumentLogOut(ORM):
    id: int
    cabinet_instrument_id: int
    instrument_name: str
    change: int
    reason: str | None
    user_id: int | None
    user_name: str | None
    created_at: datetime


class InventoryOverview(BaseModel):
    cabinet_id: int
    cabinet_name: str
    total_kinds: int
    total_units: int
    available: list[CabinetItemOut]
    low_stock: list[CabinetItemOut]
    broken: list[CabinetItemOut]
    missing: list[InstrumentOut]
