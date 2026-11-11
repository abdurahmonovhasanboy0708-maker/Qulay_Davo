"""Django'ning changepassword analogi:  python -m app.scripts.set_password"""
import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import User
from app.schemas import normalize_phone


def main() -> None:
    try:
        phone = normalize_phone(input("Telefon (+998...): ").strip())
    except ValueError as e:
        sys.exit(f"Xato: {e}")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == phone))
        if not user:
            sys.exit("Bunday foydalanuvchi topilmadi.")
        password = getpass.getpass(f"{user.full_name} uchun yangi parol (6+ belgi): ")
        if not 6 <= len(password) <= 72:
            sys.exit("Xato: parol 6-72 ta belgi bo'lishi kerak.")
        if password != getpass.getpass("Parolni takrorlang: "):
            sys.exit("Xato: parollar mos kelmadi.")
        user.password_hash = hash_password(password)
        db.commit()
        print("Parol almashtirildi.")


if __name__ == "__main__":
    main()
