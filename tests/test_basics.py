import pytest

from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.schemas import normalize_phone


@pytest.mark.parametrize("raw", ["+998 90 123-45-67", "901234567", "998901234567", "+998(90)1234567"])
def test_phone_normalized(raw):
    assert normalize_phone(raw) == "998901234567"


@pytest.mark.parametrize("raw", ["123", "+79001234567", "abc"])
def test_phone_invalid(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_password_hash():
    h = hash_password("secret123")
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip():
    payload = decode_token(create_access_token(42, "patient"))
    assert payload["sub"] == "42" and payload["role"] == "patient"
