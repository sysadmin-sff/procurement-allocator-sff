import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material


class ProjectTemplate(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "project_templates"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    items: Mapped[list["ProjectTemplateItem"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class ProjectTemplateItem(UUIDPKMixin, Base):
    __tablename__ = "project_template_items"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_templates.id", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )

    template: Mapped["ProjectTemplate"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship()
