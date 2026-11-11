from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, StaffUser
from app.models import (
    Cabinet, CabinetInstrument, Instrument, InstrumentLog, InstrumentStatus, Role, User,
)
from app.schemas import (
    CabinetItemCreate, CabinetItemOut, CabinetItemUpdate, InstrumentIn, InstrumentLogOut,
    InstrumentOut, InventoryOverview,
)

router = APIRouter(tags=["Inventory"])


def _cabinet_or_404(db, cabinet_id: int) -> Cabinet:
    cabinet = db.get(Cabinet, cabinet_id)
    if not cabinet:
        raise HTTPException(404, "Kabinet topilmadi")
    return cabinet


def _check_access(user: User, cabinet_id: int, write: bool = False) -> None:
    """Admin - hamma kabinet; shifokor - faqat o'zining kabineti; registrator - faqat o'qish."""
    if user.role == Role.admin:
        return
    if user.role == Role.doctor and user.doctor and user.doctor.cabinet_id == cabinet_id:
        return
    if user.role == Role.receptionist and not write:
        return
    raise HTTPException(403, "Bu kabinet inventariga ruxsatingiz yo'q")


def _item_or_404(db, cabinet_id: int, item_id: int) -> CabinetInstrument:
    item = db.get(CabinetInstrument, item_id)
    if not item or item.cabinet_id != cabinet_id:
        raise HTTPException(404, "Asbob bu kabinetda topilmadi")
    return item


def _items(db, cabinet_id: int) -> list[CabinetInstrument]:
    q = (select(CabinetInstrument).join(Instrument)
         .options(selectinload(CabinetInstrument.instrument))
         .where(CabinetInstrument.cabinet_id == cabinet_id)
         .order_by(Instrument.name))
    return list(db.scalars(q).all())


# ---------- Asboblar katalogi ----------
@router.get("/instruments", response_model=list[InstrumentOut])
def catalog(db: DB, _: StaffUser):
    return db.scalars(select(Instrument).order_by(Instrument.name)).all()


@router.post("/instruments", response_model=InstrumentOut, status_code=201)
def create_instrument(data: InstrumentIn, db: DB, user: StaffUser):
    if user.role == Role.receptionist:
        raise HTTPException(403, "Bu amal uchun ruxsat yo'q")
    if db.scalar(select(Instrument).where(func.lower(Instrument.name) == data.name.lower())):
        raise HTTPException(409, "Bunday asbob katalogda bor")
    instrument = Instrument(name=data.name, category=data.category)
    db.add(instrument)
    db.commit()
    return instrument


# ---------- Kabinet inventari ----------
@router.get("/cabinets/{cabinet_id}/instruments", response_model=list[CabinetItemOut])
def list_items(cabinet_id: int, db: DB, user: StaffUser,
               status: InstrumentStatus | None = None):
    _cabinet_or_404(db, cabinet_id)
    _check_access(user, cabinet_id)
    items = _items(db, cabinet_id)
    return [i for i in items if status is None or i.status == status]


@router.get("/cabinets/{cabinet_id}/instruments/overview", response_model=InventoryOverview)
def overview(cabinet_id: int, db: DB, user: StaffUser):
    """Nima bor, nima kam qolgan, nima buzuq va nima umuman yo'q - bitta javobda."""
    cabinet = _cabinet_or_404(db, cabinet_id)
    _check_access(user, cabinet_id)
    items = _items(db, cabinet_id)
    present = [i for i in items if i.quantity > 0]
    present_ids = {i.instrument_id for i in present}
    catalog_ = db.scalars(select(Instrument).order_by(Instrument.name)).all()
    return {
        "cabinet_id": cabinet.id,
        "cabinet_name": cabinet.name,
        "total_kinds": len(present),
        "total_units": sum(i.quantity for i in present),
        "available": present,
        "low_stock": [i for i in present if i.is_low],
        "broken": [i for i in items if i.status == InstrumentStatus.broken],
        "missing": [c for c in catalog_ if c.id not in present_ids],
    }


@router.get("/cabinets/{cabinet_id}/instruments/low-stock", response_model=list[CabinetItemOut])
def low_stock(cabinet_id: int, db: DB, user: StaffUser):
    _cabinet_or_404(db, cabinet_id)
    _check_access(user, cabinet_id)
    return [i for i in _items(db, cabinet_id) if i.is_low]


@router.get("/cabinets/{cabinet_id}/instruments/logs", response_model=list[InstrumentLogOut])
def logs(cabinet_id: int, db: DB, user: StaffUser,
         limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _cabinet_or_404(db, cabinet_id)
    _check_access(user, cabinet_id)
    q = (select(InstrumentLog).join(CabinetInstrument)
         .where(CabinetInstrument.cabinet_id == cabinet_id)
         .options(selectinload(InstrumentLog.cabinet_instrument).selectinload(CabinetInstrument.instrument),
                  selectinload(InstrumentLog.user))
         .order_by(InstrumentLog.created_at.desc(), InstrumentLog.id.desc())
         .limit(limit).offset(offset))
    return db.scalars(q).all()


@router.post("/cabinets/{cabinet_id}/instruments", response_model=CabinetItemOut, status_code=201)
def add_item(cabinet_id: int, data: CabinetItemCreate, db: DB, user: StaffUser):
    """Kabinetga asbob qo'shish. Katalogda yo'q bo'lsa, name bilan avtomatik yaratiladi."""
    _cabinet_or_404(db, cabinet_id)
    _check_access(user, cabinet_id, write=True)
    if data.instrument_id:
        instrument = db.get(Instrument, data.instrument_id)
        if not instrument:
            raise HTTPException(404, "Asbob katalogda topilmadi")
    else:
        instrument = db.scalar(select(Instrument).where(func.lower(Instrument.name) == data.name.lower()))
        if not instrument:
            instrument = Instrument(name=data.name, category=data.category)
            db.add(instrument)
            db.flush()
    exists = db.scalar(select(CabinetInstrument).where(
        CabinetInstrument.cabinet_id == cabinet_id,
        CabinetInstrument.instrument_id == instrument.id))
    if exists:
        raise HTTPException(409, "Bu asbob kabinetda bor. Sonini PATCH bilan o'zgartiring")
    item = CabinetInstrument(cabinet_id=cabinet_id, instrument_id=instrument.id,
                             quantity=data.quantity, min_quantity=data.min_quantity,
                             status=data.status)
    db.add(item)
    db.flush()
    db.add(InstrumentLog(cabinet_instrument_id=item.id, change=data.quantity,
                         reason="Kabinetga qo'shildi", user_id=user.id))
    db.commit()
    db.refresh(item)
    return item


@router.patch("/cabinets/{cabinet_id}/instruments/{item_id}", response_model=CabinetItemOut)
def update_item(cabinet_id: int, item_id: int, data: CabinetItemUpdate, db: DB, user: StaffUser):
    _cabinet_or_404(db, cabinet_id)
    _check_access(user, cabinet_id, write=True)
    item = _item_or_404(db, cabinet_id, item_id)

    notes: list[str] = []
    change = 0
    if data.quantity is not None and data.quantity != item.quantity:
        change = data.quantity - item.quantity
        notes.append(f"soni {item.quantity} -> {data.quantity}")
        item.quantity = data.quantity
    if data.status is not None and data.status != item.status:
        notes.append(f"holati {item.status.value} -> {data.status.value}")
        item.status = data.status
    if data.min_quantity is not None and data.min_quantity != item.min_quantity:
        notes.append(f"minimum {item.min_quantity} -> {data.min_quantity}")
        item.min_quantity = data.min_quantity

    if notes:
        reason = "; ".join(notes) + (f" ({data.reason})" if data.reason else "")
        db.add(InstrumentLog(cabinet_instrument_id=item.id, change=change,
                             reason=reason[:255], user_id=user.id))
        db.commit()
        db.refresh(item)
    return item
