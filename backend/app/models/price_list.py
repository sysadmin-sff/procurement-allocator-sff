import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.price import Price
    from app.models.supplier import Supplier


class PriceListImport(UUIDPKMixin, Base):
    __tablename__ = "price_list_imports"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    file_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    """pending_review/approved/rejected"""
    parsed_by_ai_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped["Supplier"] = relationship(back_populates="price_list_imports")
    entries: Mapped[list["PriceListEntry"]] = relationship(back_populates="import_")
    prices: Mapped[list["Price"]] = relationship(back_populates="source_import")


class PriceListEntry(UUIDPKMixin, Base):
    __tablename__ = "price_list_entries"

    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_list_imports.id"), nullable=False
    )
    supplier_raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_sku: Mapped[str | None] = mapped_column(String(100))
    matched_material_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id")
    )
    """nullable — новый материал?"""
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    reasoning: Mapped[str | None] = mapped_column(String(2000))
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    availability: Mapped[int | None] = mapped_column()
    min_order_qty: Mapped[int | None] = mapped_column()
    action: Mapped[str | None] = mapped_column(String(20))
    """match/new/skip — заполняется при применении строки на экране ревью,
    см. ADR-0019 §5. NULL = ещё не решено."""

    import_: Mapped["PriceListImport"] = relationship(back_populates="entries")
    matched_material: Mapped["Material | None"] = relationship(
        back_populates="price_list_entries"
    )
