"""Eskiz.uz orqali SMS yuborish. Kalitlar berilmasa - dry-run (faqat logga yozadi)."""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
BASE = "https://notify.eskiz.uz/api"
_token: str | None = None


def _login(client: httpx.Client) -> str:
    global _token
    r = client.post(f"{BASE}/auth/login",
                    data={"email": settings.eskiz_email, "password": settings.eskiz_password})
    r.raise_for_status()
    _token = r.json()["data"]["token"]
    return _token


def send_sms(phone: str, text: str) -> None:
    if not settings.eskiz_email:
        logger.info("[DRY-RUN SMS] %s: %s", phone, text)
        return
    with httpx.Client(timeout=10) as client:
        for attempt in (1, 2):
            token = _token or _login(client)
            r = client.post(
                f"{BASE}/message/sms/send",
                headers={"Authorization": f"Bearer {token}"},
                data={"mobile_phone": phone, "message": text, "from": settings.eskiz_sender},
            )
            if r.status_code == 401 and attempt == 1:
                _login(client)  # token eskirgan - qayta kirib, yana urinamiz
                continue
            r.raise_for_status()
            return
