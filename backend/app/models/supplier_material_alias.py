import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.supplier import Supplier
    from app.models.user import User


class SupplierMaterialAlias(UUIDPKMixin, Base):
    __tablename__ = "supplier_material_aliases"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(100))
    supplier_raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="price_import")
    """'price_import' (price-list ingestion review, ADR-0019 §2) |
    'order_response' (the "Связать" button on the order-response review
    screen, ADR-0046). find_known_alias (price-ingestion short-circuit)
    only ever reads 'price_import' rows — an order-response alias is
    confirmed in the context of one specific order's reply document, not
    as a general statement about this supplier's price-list vocabulary,
    so it must not silently start resolving a Price. See ADR-0046 §4."""
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    """Who created this alias — NULL for rows that predate ADR-0046 (every
    row created via price-ingestion's _upsert_alias before this column
    existed). SET NULL, not CASCADE: deleting the user must not delete the
    alias — it is a durable business fact, not scoped to its author's
    account. See ADR-0046 §3."""
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """NULL for rows that predate ADR-0046 — their actual creation time was
    never recorded anywhere, and backfilling the migration's run date
    would be a fabricated fact, not a real one. See ADR-0046 §3."""

    supplier: Mapped["Supplier"] = relationship(back_populates="aliases")
    material: Mapped["Material"] = relationship(back_populates="aliases")
    created_by: Mapped["User | None"] = relationship()
