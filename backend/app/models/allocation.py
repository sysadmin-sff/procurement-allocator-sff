import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.project import Project
    from app.models.supplier import Supplier


class AllocationRun(UUIDPKMixin, Base):
    __tablename__ = "allocation_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    algorithm_version: Mapped[str | None] = mapped_column(String(50))
    orphaned_materials: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    """Материалы, недостижимые ни у одного поставщика — см. ADR-0002.
    Список объектов {material_id, required_quantity, best_partial_supplier_id,
    best_partial_available}, чисто информационный для UI, не участвует в расчётах."""

    project: Mapped["Project"] = relationship(back_populates="allocation_runs")
    lines: Mapped[list["AllocationLine"]] = relationship(back_populates="allocation_run")


class AllocationLine(UUIDPKMixin, Base):
    __tablename__ = "allocation_lines"

    allocation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("allocation_runs.id"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    allocation_run: Mapped["AllocationRun"] = relationship(back_populates="lines")
    material: Mapped["Material"] = relationship()
    supplier: Mapped["Supplier"] = relationship(back_populates="allocation_lines")
