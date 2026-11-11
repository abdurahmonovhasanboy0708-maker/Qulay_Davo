"""Demo ma'lumotlar:  python -m app.scripts.seed"""
from datetime import time

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Cabinet, CabinetInstrument, Doctor, Instrument, InstrumentLog, Role, User, WorkSchedule,
)

INSTRUMENTS = [
    ("Stomatologik ko'zgu", "Diagnostika", 10, 4),
    ("Zond", "Diagnostika", 8, 3),
    ("Pinset", "Diagnostika", 6, 2),
    ("Ekskavator", "Terapiya", 5, 2),
    ("Shpris", "Anesteziya", 3, 5),   # min dan kam -> "kam qoldi"
    ("Skalpel", "Jarrohlik", 4, 2),
]
# katalogda bor, lekin kabinetda yo'q (overview -> missing ro'yxatida chiqadi)
ONLY_IN_CATALOG = [("Elevator", "Jarrohlik"), ("Kyuretaj qoshig'i", "Terapiya")]


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.phone == "998900000001")):
            print("Seed allaqachon bajarilgan.")
            return

        admin = User(phone="998900000001", full_name="Admin", role=Role.admin,
                     password_hash=hash_password("admin123"))
        patient = User(phone="998900000003", full_name="Test Bemor", role=Role.patient,
                       password_hash=hash_password("patient123"))
        doc_user = User(phone="998900000002", full_name="Dr. Aliyev Bobur", role=Role.doctor,
                        password_hash=hash_password("doctor123"))
        cabinet = Cabinet(name="Kabinet 101", floor=1)
        db.add_all([admin, patient, doc_user, cabinet])
        db.flush()

        doctor = Doctor(user_id=doc_user.id, specialty="Stomatolog",
                        cabinet_id=cabinet.id, slot_minutes=30)
        db.add(doctor)
        db.flush()
        for weekday in range(5):  # Du-Ju
            db.add(WorkSchedule(doctor_id=doctor.id, weekday=weekday,
                                start_time=time(9), end_time=time(13)))
            db.add(WorkSchedule(doctor_id=doctor.id, weekday=weekday,
                                start_time=time(14), end_time=time(18)))

        for name, category, qty, min_qty in INSTRUMENTS:
            instrument = Instrument(name=name, category=category)
            db.add(instrument)
            db.flush()
            item = CabinetInstrument(cabinet_id=cabinet.id, instrument_id=instrument.id,
                                     quantity=qty, min_quantity=min_qty)
            db.add(item)
            db.flush()
            db.add(InstrumentLog(cabinet_instrument_id=item.id, change=qty,
                                 reason="Seed: boshlang'ich", user_id=admin.id))
        for name, category in ONLY_IN_CATALOG:
            db.add(Instrument(name=name, category=category))

        db.commit()
        print("Tayyor!")
        print("  admin   : 998900000001 / admin123")
        print("  shifokor: 998900000002 / doctor123")
        print("  bemor   : 998900000003 / patient123")


if __name__ == "__main__":
    main()
