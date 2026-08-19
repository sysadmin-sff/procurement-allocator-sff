import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.office import Office
    from app.models.supplier import Supplier


class SupplierContact(UUIDPKMixin, Base):
    __tablename__ = "supplier_contacts"

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offices.id", ondelete="SET NULL")
    )
    """Nullable — не у каждого контакта есть чёткая привязка к одному офису.
    supplier_id дублирует office->supplier намеренно, см. ADR-0010 п.2."""
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))

    supplier: Mapped["Supplier"] = relationship(back_populates="contacts_directory")
    office: Mapped["Office | None"] = relationship(back_populates="contacts")
