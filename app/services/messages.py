from app.core.config import settings
from app.models import Appointment


def format_appointment(appt: Appointment) -> str:
    local = appt.start_at.astimezone(settings.tz)
    cabinet = f"\nKabinet: {appt.cabinet_name}" if appt.cabinet_name else ""
    return (
        f"Shifokor: {appt.doctor_name} ({appt.specialty})\n"
        f"Vaqt: {local:%d.%m.%Y %H:%M}{cabinet}"
    )


def reminder_text(appt: Appointment, kind: str) -> str:
    minutes = int(kind.split("_")[1])
    return f"Qulay Davo: navbatingizga {minutes} daqiqa qoldi.\n{format_appointment(appt)}"


def queue_text(appt: Appointment, ahead: int) -> str:
    """Soatlik xabar: sizdan oldin necha kishi bor va taxminiy qabul vaqti."""
    local = appt.start_at.astimezone(settings.tz)
    who = ("Sizdan oldin navbatda hech kim yo'q" if ahead == 0
           else f"Sizdan oldin {ahead} kishi bor")
    cabinet = f"\nKabinet: {appt.cabinet_name}" if appt.cabinet_name else ""
    return (
        "Qulay Davo: bugungi navbatingiz holati.\n"
        f"{who}.\n"
        f"Taxminiy qabul vaqti: {local:%H:%M}\n"
        f"Shifokor: {appt.doctor_name} ({appt.specialty}){cabinet}"
    )
