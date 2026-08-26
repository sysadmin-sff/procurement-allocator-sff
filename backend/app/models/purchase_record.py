import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.project import Project
    from app.models.supplier import Supplier
    from app.models.user import User


class PurchaseRecord(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "purchase_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    """Название, как его вводит сотрудник, глядя на счёт/переписку поставщика.
    Не обязано матчиться на Material.canonical_name или SupplierMaterialAlias
    — см. ADR-0008 п.1."""
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id")
    )
    """Опциональная, не блокирующая аннотация — сотрудник ставит вручную, если
    узнаёт материал. Не участвует ни в каком расчёте этого ADR. См. ADR-0008 п.1."""
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Кто внёс эту запись о фактической закупке — заполняется в
    create_purchase_record. Nullable ради строк, созданных до ADR-0024.
    См. ADR-0024 §6."""

    project: Mapped["Project"] = relationship()
    supplier: Mapped["Supplier"] = relationship()
    material: Mapped["Material | None"] = relationship()
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])
