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
    from app.models.user import User


class AllocationRun(UUIDPKMixin, Base):
    __tablename__ = "allocation_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    algorithm_version: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    """'ok' — модель решена, lines/supplier_summaries заполнены. 'infeasible' —
    CP-SAT не нашёл допустимого назначения (или M_solvable пуст на входе) —
    lines/supplier_summaries пустые, попытка расчёта тем не менее сохранена.
    См. ADR-0003."""
    orphaned_materials: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    """Материалы, недостижимые ни у одного поставщика — см. ADR-0002.
    Список объектов {material_id, required_quantity, best_partial_supplier_id,
    best_partial_available}, чисто информационный для UI, не участвует в расчётах."""
    supplier_summaries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    """Сводка доставки по каждому задействованному поставщику — экспорт
    order_total[s]/free[s] из ADR-0002, которые солвер иначе считает только
    внутри модели. Список объектов {supplier_id, goods_total, delivery_fee,
    free_shipping_achieved}, снимок на момент run_allocation()."""
    split_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    """Строгие категории (STRICT_CATEGORIES, ADR-0028), фактически оказавшиеся
    разбитыми между >1 поставщиком в текущем состоянии строк проекта — список
    названий категорий (например ["Doors"]). Пересчитывается после
    run_allocation() и после каждого override_allocation_line_supplier(), той
    же точкой, что supplier_summaries (ADR-0006 §4). Чисто информационное для
    UI-предупреждения, не участвует в дальнейших расчётах."""

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
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Не NULL, если поставщик строки был вручную переопределён пользователем
    после run_allocation() — см. ADR-0006. NULL = строка в исходном
    ILP-состоянии."""
    overridden_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Кто выполнил ручной override поставщика этой строки — заполняется в
    override_allocation_line_supplier (оба пути: обычный ручной override и
    replace_and_sync_order). NULL, если overridden_at NULL (строка ни разу
    не переопределялась) или строка создана до ADR-0024. См. ADR-0024 §6."""
    original_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id")
    )
    original_unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    """supplier_id/unit_price до первого override — не перезаписываются при
    повторном override той же строки, чтобы бейдж "не самая дешёвая цена"
    мог всегда сравнить с настоящим ILP-решением. См. ADR-0006 п.1."""
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Не NULL, если строка вошла в Order, созданный из этого run — см.
    ADR-0007 п.2. Не блокирует дальнейший override (ADR-0006): если строка
    переопределена позже (overridden_at > ordered_at), это сигнал для UI,
    что уже созданный Order расходится с текущим состоянием строки, не
    запрет на правку."""
    overridden_via_order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="SET NULL")
    )
    """Не NULL, если текущий override этой строки был выполнен из
    find-replacement-флоу declined-позиции (ADR-0014 п.3) — ссылка на тот
    OrderItem. Однонаправленная связь AllocationLine -> OrderItem, не
    нарушает ADR-0007 п.2 (OrderItem по-прежнему не хранит
    allocation_line_id). Обычный ручной override (ADR-0006, без
    source_order_item_id) всегда сбрасывает это поле в NULL — точный
    причинный признак "перенесено из-за этого отказа", не эвристика по
    timestamp'ам overridden_at > declined_at."""

    allocation_run: Mapped["AllocationRun"] = relationship(back_populates="lines")
    material: Mapped["Material"] = relationship()
    supplier: Mapped["Supplier"] = relationship(
        back_populates="allocation_lines", foreign_keys=[supplier_id]
    )
    original_supplier: Mapped["Supplier | None"] = relationship(foreign_keys=[original_supplier_id])
    overridden_by: Mapped["User | None"] = relationship(foreign_keys=[overridden_by_user_id])
