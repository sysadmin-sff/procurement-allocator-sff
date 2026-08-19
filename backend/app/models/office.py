import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.supplier import Supplier
    from app.models.supplier_contact import SupplierContact


class Office(UUIDPKMixin, Base):
    __tablename__ = "offices"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(String(255))
    """Может быть шире одного адреса (например, обслуживаемый регион) — см. ADR-0010."""

    supplier: Mapped["Supplier"] = relationship(back_populates="offices")
    contacts: Mapped[list["SupplierContact"]] = relationship(back_populates="office")
