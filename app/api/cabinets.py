from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DB, AdminUser, StaffUser
from app.models import Cabinet
from app.schemas import CabinetIn, CabinetOut

router = APIRouter(prefix="/cabinets", tags=["Cabinets"])


@router.get("", response_model=list[CabinetOut])
def list_cabinets(db: DB, _: StaffUser):
    return db.scalars(select(Cabinet).order_by(Cabinet.floor, Cabinet.name)).all()


@router.post("", response_model=CabinetOut, status_code=201)
def create_cabinet(data: CabinetIn, db: DB, _: AdminUser):
    if db.scalar(select(Cabinet).where(Cabinet.name == data.name)):
        raise HTTPException(409, "Bunday nomli kabinet bor")
    cabinet = Cabinet(name=data.name, floor=data.floor)
    db.add(cabinet)
    db.commit()
    return cabinet
