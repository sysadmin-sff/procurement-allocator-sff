import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.project import Project
    from app.models.supplier import Supplier
    from app.models.user import User


class Order(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    """draft/approved/sent"""
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    delivery_fee: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    file_ref: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Кто создал этот Order — заполняется в create_orders_for_run. Nullable
    ради строк, созданных до ADR-0024. См. ADR-0024 §6."""

    project: Mapped["Project"] = relationship(back_populates="orders")
    supplier: Mapped["Supplier"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])


class OrderItem(UUIDPKMixin, Base):
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    quoted_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    """Снимок AllocationLine.unit_price на момент создания Order — что мы
    рассчитали и отправили поставщику. См. ADR-0007 п.1."""
    confirmed_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    """То, что реально подтвердил поставщик — вводится сотрудником вручную
    после ответа. NULL = ещё не сверено, не "подтверждено с ценой 0"."""
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Когда сотрудник ввёл confirmed_price. Сбрасывается в NULL, если
    confirmed_price явно очищен."""
    received_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    """Цена, которую поставщик прислал первым, до торга. NULL = ответа ещё
    нет. Независимо от confirmed_price — может быть заполнено без него и
    наоборот. См. ADR-0013."""
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Когда сотрудник явно пометил позицию как "поставщик не может
    выполнить/нет в наличии". NULL = не отмечено (не значит "доступно").
    Не эксклюзивно с received_price/confirmed_price — обе группы полей
    могут быть заполнены одновременно (напр. отказался, но предложил
    замену по другой цене). См. ADR-0013 п.2."""
    decline_reason: Mapped[str | None] = mapped_column(String(500))
    """Свободный текст, необязательный. См. ADR-0013 п.2."""

    order: Mapped["Order"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship()
