"""initial schema + no-overlap constraint

Revision ID: 0001
Revises:
"""
from alembic import op

from app.db.base import Base
import app.models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist: gist indeksida oddiy tenglik (doctor_id =) va oraliq (&&) ni birga ishlatish uchun
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # Boshlang'ich (baseline) sxema. Keyingi o'zgarishlar uchun:
    #   alembic revision --autogenerate -m "..."
    Base.metadata.create_all(bind=op.get_bind())
    # Bir shifokorning faol ('booked') navbatlari vaqt bo'yicha kesishishi MUMKIN EMAS.
    # Ikki bemor bir vaqtda band qilsa ham, DB ikkinchisini rad etadi (race condition yo'q).
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT appointments_no_overlap
        EXCLUDE USING gist (
            doctor_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        ) WHERE (status = 'booked')
        """
    )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
