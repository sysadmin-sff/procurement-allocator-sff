import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.allocation import AllocationRun
    from app.models.material import Material
    from app.models.order import Order


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    items: Mapped[list["ProjectItem"]] = relationship(back_populates="project")
    allocation_runs: Mapped[list["AllocationRun"]] = relationship(back_populates="project")
    orders: Mapped[list["Order"]] = relationship(back_populates="project")


class ProjectItem(UUIDPKMixin, Base):
    __tablename__ = "project_items"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)

    project: Mapped["Project"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship(back_populates="project_items")
