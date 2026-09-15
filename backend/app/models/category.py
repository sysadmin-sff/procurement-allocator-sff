from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material


class Category(UUIDPKMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    sku_prefix: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    """Immutable after creation — see ADR-0034 п.5. internal_sku values already
    issued embed this prefix; CategoryUpdate has no field for it at all."""
    requires_single_supplier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    """Drives ADR-0028 strict-category ILP grouping in solver.py — replaces the
    old STRICT_CATEGORIES code constant. See ADR-0034."""
    next_sku_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Atomically incremented via UPDATE ... RETURNING in the same transaction
    as Material creation — see ADR-0034 п.4. Never read-then-written as two
    separate statements."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    materials: Mapped[list["Material"]] = relationship(back_populates="category")
