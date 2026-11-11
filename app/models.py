import enum
from datetime import datetime, time

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index,
    String, Text, Time, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Role(str, enum.Enum):
    admin = "admin"
    doctor = "doctor"
    receptionist = "receptionist"
    patient = "patient"


class AppointmentStatus(str, enum.Enum):
    booked = "booked"
    cancelled = "cancelled"
    done = "done"
    no_show = "no_show"


class Channel(str, enum.Enum):
    sms = "sms"
    telegram = "telegram"


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class InstrumentStatus(str, enum.Enum):
    available = "available"
    in_use = "in_use"
    sterilizing = "sterilizing"
    broken = "broken"


def _enum(e: type[enum.Enum]) -> SAEnum:
    # VARCHAR sifatida saqlanadi (native PG enum emas) - migratsiyalar osonroq bo'ladi
    return SAEnum(e, native_enum=False, length=20, values_callable=lambda x: [i.value for i in x])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.patient)
    is_active: Mapped[bool] = mapped_column(default=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    doctor: Mapped["Doctor | None"] = relationship(back_populates="user", uselist=False)


class Cabinet(Base):
    __tablename__ = "cabinets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    floor: Mapped[int] = mapped_column(default=1)

    doctors: Mapped[list["Doctor"]] = relationship(back_populates="cabinet")
    items: Mapped[list["CabinetInstrument"]] = relationship(back_populates="cabinet")


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    specialty: Mapped[str] = mapped_column(String(100), index=True)
    cabinet_id: Mapped[int | None] = mapped_column(ForeignKey("cabinets.id", ondelete="SET NULL"))
    slot_minutes: Mapped[int] = mapped_column(default=30)

    user: Mapped[User] = relationship(back_populates="doctor")
    cabinet: Mapped["Cabinet | None"] = relationship(back_populates="doctors")
    schedules: Mapped[list["WorkSchedule"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return self.user.full_name

    @property
    def cabinet_name(self) -> str | None:
        return self.cabinet.name if self.cabinet else None


class WorkSchedule(Base):
    """Shifokorning haftalik ish vaqti. weekday: 0=Dushanba ... 6=Yakshanba.
    Tushlik tanaffusi uchun bir kunga bir nechta oraliq qo'shish mumkin."""

    __tablename__ = "work_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int]
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_schedule_weekday"),
        CheckConstraint("end_time > start_time", name="ck_schedule_time"),
    )


class Appointment(Base):
    """Navbat. Bir shifokorning 'booked' navbatlari kesishmasligi PostgreSQL darajasida
    EXCLUDE constraint bilan kafolatlanadi (alembic/versions/0001 ga qarang)."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        _enum(AppointmentStatus), default=AppointmentStatus.booked
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped[User] = relationship(foreign_keys=[patient_id])
    doctor: Mapped[Doctor] = relationship()
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="appointment", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_appointments_doctor_start", "doctor_id", "start_at"),)

    @property
    def patient_name(self) -> str:
        return self.patient.full_name

    @property
    def doctor_name(self) -> str:
        return self.doctor.full_name

    @property
    def specialty(self) -> str:
        return self.doctor.specialty

    @property
    def cabinet_name(self) -> str | None:
        return self.doctor.cabinet_name


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"))
    channel: Mapped[Channel] = mapped_column(_enum(Channel))
    kind: Mapped[str] = mapped_column(String(20))  # before_60 / before_30
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[NotificationStatus] = mapped_column(
        _enum(NotificationStatus), default=NotificationStatus.pending
    )
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    appointment: Mapped[Appointment] = relationship(back_populates="notifications")

    __table_args__ = (Index("ix_notifications_due", "status", "send_at"),)


class Instrument(Base):
    """Asboblar katalogi (umumiy ro'yxat)."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str | None] = mapped_column(String(60))


class CabinetInstrument(Base):
    """Muayyan kabinetdagi asbob: nechta bor, holati qanday."""

    __tablename__ = "cabinet_instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    quantity: Mapped[int] = mapped_column(default=0)
    min_quantity: Mapped[int] = mapped_column(default=1)
    status: Mapped[InstrumentStatus] = mapped_column(
        _enum(InstrumentStatus), default=InstrumentStatus.available
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cabinet: Mapped[Cabinet] = relationship(back_populates="items")
    instrument: Mapped[Instrument] = relationship()

    __table_args__ = (
        UniqueConstraint("cabinet_id", "instrument_id", name="uq_cabinet_instrument"),
        CheckConstraint("quantity >= 0", name="ck_quantity_nonneg"),
        CheckConstraint("min_quantity >= 0", name="ck_min_quantity_nonneg"),
    )

    @property
    def name(self) -> str:
        return self.instrument.name

    @property
    def category(self) -> str | None:
        return self.instrument.category

    @property
    def is_low(self) -> bool:
        return self.quantity <= self.min_quantity


class InstrumentLog(Base):
    """Audit: kim, qachon, nimani o'zgartirdi."""

    __tablename__ = "instrument_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    cabinet_instrument_id: Mapped[int] = mapped_column(
        ForeignKey("cabinet_instruments.id", ondelete="CASCADE"), index=True
    )
    change: Mapped[int] = mapped_column(default=0)
    reason: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cabinet_instrument: Mapped[CabinetInstrument] = relationship()
    user: Mapped["User | None"] = relationship()

    @property
    def instrument_name(self) -> str:
        return self.cabinet_instrument.instrument.name

    @property
    def user_name(self) -> str | None:
        return self.user.full_name if self.user else None
