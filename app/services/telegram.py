"""Telegram Bot API orqali xabar yuborish (Celery ishchisi uchun, sinxron)."""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_telegram(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        logger.info("[DRY-RUN TELEGRAM] %s: %s", chat_id, text)
        return
    r = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    r.raise_for_status()
