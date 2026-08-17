import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.price_list import PriceListImport
    from app.models.supplier import Supplier


class Price(UUIDPKMixin, Base):
    __tablename__ = "prices"

    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    availability: Mapped[int | None] = mapped_column()
    min_order_qty: Mapped[int | None] = mapped_column()
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    """NULL = текущая действующая цена; при обновлении закрывается, не удаляется"""
    source_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_list_imports.id")
    )

    material: Mapped["Material"] = relationship(back_populates="prices")
    supplier: Mapped["Supplier"] = relationship(back_populates="prices")
    source_import: Mapped["PriceListImport | None"] = relationship(back_populates="prices")
