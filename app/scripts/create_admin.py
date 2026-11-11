"""Django'ning createsuperuser analogi:  python -m app.scripts.create_admin"""
import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Role, User
from app.schemas import normalize_phone


def main() -> None:
    try:
        phone = normalize_phone(input("Telefon (+998...): ").strip())
    except ValueError as e:
        sys.exit(f"Xato: {e}")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == phone))
        if user:
            if input(f"{user.full_name} ({user.role.value}) allaqachon bor. Admin qilaymi? [y/N]: ").lower() != "y":
                sys.exit("Bekor qilindi.")
            user.role = Role.admin
            db.commit()
            sys.exit(f"Tayyor: {user.full_name} endi admin.")

        name = input("Ism-familiya: ").strip()
        password = getpass.getpass("Parol (6+ belgi): ")
        if len(name) < 2 or not 6 <= len(password) <= 72:
            sys.exit("Xato: ism kamida 2 ta, parol 6-72 ta belgi bo'lishi kerak.")
        if password != getpass.getpass("Parolni takrorlang: "):
            sys.exit("Xato: parollar mos kelmadi.")

        db.add(User(phone=phone, full_name=name, role=Role.admin,
                    password_hash=hash_password(password)))
        db.commit()
        print(f"Tayyor: admin {name} ({phone}) yaratildi.")


if __name__ == "__main__":
    main()
