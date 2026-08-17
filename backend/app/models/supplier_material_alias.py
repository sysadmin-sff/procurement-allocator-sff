import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.supplier import Supplier


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

    supplier: Mapped["Supplier"] = relationship(back_populates="aliases")
    material: Mapped["Material"] = relationship(back_populates="aliases")
