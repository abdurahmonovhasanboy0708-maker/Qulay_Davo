from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "qulay_davo",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    timezone="UTC",
    task_ignore_result=True,
    beat_schedule={
        # har daqiqada vaqti kelgan eslatmalarni yuboradi (60 va 30 daqiqa oldin)
        "dispatch-due-notifications": {
            "task": "app.worker.tasks.dispatch_due_notifications",
            "schedule": 60.0,
        },
        # har soat boshida (:00) navbat holati: oldingizda necha kishi, taxminiy vaqt
        "hourly-queue-updates": {
            "task": "app.worker.tasks.send_queue_updates",
            "schedule": crontab(minute=0),
        },
    },
)
