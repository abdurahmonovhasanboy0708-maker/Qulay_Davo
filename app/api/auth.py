from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Role, User
from app.schemas import RegisterIn, TokenOut, UserOut, normalize_phone

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, db: DB):
    """Bemor sifatida ro'yxatdan o'tish. Shifokorlarni faqat admin qo'sha oladi."""
    if db.scalar(select(User).where(User.phone == data.phone)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu raqam allaqachon ro'yxatdan o'tgan")
    user = User(phone=data.phone, full_name=data.full_name,
                password_hash=hash_password(data.password), role=Role.patient)
    db.add(user)
    db.commit()
    return user


@router.post("/login", response_model=TokenOut)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB):
    """username maydoniga telefon raqamni kiriting."""
    bad = HTTPException(status.HTTP_401_UNAUTHORIZED, "Telefon yoki parol noto'g'ri")
    try:
        phone = normalize_phone(form.username)
    except ValueError:
        raise bad
    user = db.scalar(select(User).where(User.phone == phone))
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        raise bad
    return TokenOut(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
