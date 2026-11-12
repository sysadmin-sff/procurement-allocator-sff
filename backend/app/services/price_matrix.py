"""Матрица цен «все материалы × все поставщики» и история пары (ADR-0054).

Чистое чтение: ничего не пишет. Всё сравнение (направление, процент,
самая дешёвая, счётчики) считается здесь, frontend только отображает —
принцип 4 CLAUDE.md.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Material, Order, OrderItem, Price, PriceListImport, Supplier, User

STALE_AFTER_DAYS = 30
"""Поставщик без новых версий цен дольше этого — «давно не обновлялся»."""

Change = Literal["up", "down", "same", "new"]
Source = Literal["import", "order", "manual"]


@dataclass
class ChangeCounts:
    up: int = 0
    down: int = 0
    new: int = 0
    same: int = 0

    def add(self, change: Change) -> None:
        setattr(self, change, getattr(self, change) + 1)


@dataclass
class MatrixCell:
    supplier_id: uuid.UUID
    price_id: uuid.UUID
    price: Decimal
    currency: str
    valid_from: datetime.date
    baseline_price: Decimal | None
    baseline_valid_from: datetime.date | None
    change: Change
    change_pct: Decimal | None
    is_cheapest: bool = False


@dataclass
class MatrixRow:
    material_id: uuid.UUID
    internal_sku: str
    canonical_name: str
    unit: str
    category_name: str | None
    cells: list[MatrixCell] = field(default_factory=list)


@dataclass
class MatrixSupplier:
    id: uuid.UUID
    name: str
    short_name: str | None
    is_active_for_allocation: bool
    last_price_date: datetime.date | None
    days_since_update: int | None
    is_stale: bool
    active_price_count: int
    changes: ChangeCounts


@dataclass
class PriceMatrix:
    as_of: datetime.date
    compare_to: datetime.date | None
    stale_after_days: int
    suppliers: list[MatrixSupplier]
    rows: list[MatrixRow]
    summary: ChangeCounts


def _version_sort_key(price: Price) -> tuple:
    """Хронологический порядок версий одной пары. valid_to NULL (активная)
    — последней; среди закрытых — по valid_from, затем valid_to."""
    return (
        price.valid_to is None,
        price.valid_from,
        price.valid_to or datetime.date.max,
    )


def _baseline(
    history: list[Price], active: Price, compare_to: datetime.date | None
) -> Price | None:
    """history — все версии пары в хронологическом порядке."""
    if compare_to is None:
        older = [p for p in history if p.id != active.id and p.valid_to is not None]
        return older[-1] if older else None

    effective = [
        p
        for p in history
        if p.valid_from <= compare_to and (p.valid_to is None or p.valid_to > compare_to)
    ]
    return effective[-1] if effective else None


def _classify(current: Decimal, baseline: Price | None) -> tuple[Change, Decimal | None]:
    if baseline is None:
        return "new", None
    base = Decimal(baseline.price)
    if current > base:
        change: Change = "up"
    elif current < base:
        change = "down"
    else:
        change = "same"
    if base == 0:
        return change, None
    pct = ((current - base) / base * 100).quantize(Decimal("0.1"))
    return change, pct


def build_price_matrix(
    db: Session,
    *,
    compare_to: datetime.date | None = None,
    today: datetime.date | None = None,
) -> PriceMatrix:
    today = today or datetime.date.today()

    by_pair: dict[tuple[uuid.UUID, uuid.UUID], list[Price]] = defaultdict(list)
    last_date_by_supplier: dict[uuid.UUID, datetime.date] = {}
    for price in db.scalars(select(Price)):
        by_pair[(price.material_id, price.supplier_id)].append(price)
        current_last = last_date_by_supplier.get(price.supplier_id)
        if current_last is None or price.valid_from > current_last:
            last_date_by_supplier[price.supplier_id] = price.valid_from

    cells_by_material: dict[uuid.UUID, list[MatrixCell]] = defaultdict(list)
    counts_by_supplier: dict[uuid.UUID, ChangeCounts] = defaultdict(ChangeCounts)
    active_count_by_supplier: dict[uuid.UUID, int] = defaultdict(int)
    summary = ChangeCounts()

    for (material_id, supplier_id), history in by_pair.items():
        history.sort(key=_version_sort_key)
        active_rows = [p for p in history if p.valid_to is None]
        if not active_rows:
            continue
        active = active_rows[-1]
        current = Decimal(active.price)
        baseline = _baseline(history, active, compare_to)
        change, pct = _classify(current, baseline)

        cells_by_material[material_id].append(
            MatrixCell(
                supplier_id=supplier_id,
                price_id=active.id,
                price=current,
                currency=active.currency,
                valid_from=active.valid_from,
                baseline_price=Decimal(baseline.price) if baseline is not None else None,
                baseline_valid_from=baseline.valid_from if baseline is not None else None,
                change=change,
                change_pct=pct,
            )
        )
        counts_by_supplier[supplier_id].add(change)
        active_count_by_supplier[supplier_id] += 1
        summary.add(change)

    for cells in cells_by_material.values():
        if len(cells) < 2:
            continue
        cheapest = min(c.price for c in cells)
        for cell in cells:
            cell.is_cheapest = cell.price == cheapest

    suppliers: list[MatrixSupplier] = []
    for supplier in db.scalars(
        select(Supplier).where(Supplier.id.in_(list(active_count_by_supplier)))
    ):
        last_date = last_date_by_supplier.get(supplier.id)
        days = (today - last_date).days if last_date is not None else None
        suppliers.append(
            MatrixSupplier(
                id=supplier.id,
                name=supplier.name,
                short_name=supplier.short_name,
                is_active_for_allocation=supplier.is_active_for_allocation,
                last_price_date=last_date,
                days_since_update=days,
                is_stale=days is not None and days > STALE_AFTER_DAYS,
                active_price_count=active_count_by_supplier[supplier.id],
                changes=counts_by_supplier[supplier.id],
            )
        )
    suppliers.sort(key=lambda s: (s.short_name or s.name).lower())
    supplier_order = {s.id: index for index, s in enumerate(suppliers)}

    rows: list[MatrixRow] = []
    for material, category_name in db.execute(
        select(Material, Category.name).outerjoin(Category, Material.category_id == Category.id)
    ):
        cells = sorted(
            cells_by_material.get(material.id, []), key=lambda c: supplier_order[c.supplier_id]
        )
        rows.append(
            MatrixRow(
                material_id=material.id,
                internal_sku=material.internal_sku,
                canonical_name=material.canonical_name,
                unit=material.unit,
                category_name=category_name,
                cells=cells,
            )
        )

    return PriceMatrix(
        as_of=today,
        compare_to=compare_to,
        stale_after_days=STALE_AFTER_DAYS,
        suppliers=suppliers,
        rows=rows,
        summary=summary,
    )


@dataclass
class PriceHistoryEntry:
    id: uuid.UUID
    price: Decimal
    currency: str
    valid_from: datetime.date
    valid_to: datetime.date | None
    source: Source
    import_id: uuid.UUID | None
    import_uploaded_at: datetime.datetime | None
    order_id: uuid.UUID | None
    order_title: str | None
    created_by_name: str | None
    change: Change | None
    """Относительно предыдущей (более старой) версии; None у самой первой."""


def price_history(
    db: Session, *, material_id: uuid.UUID, supplier_id: uuid.UUID
) -> list[PriceHistoryEntry]:
    """Все версии пары, новые первыми, с источником каждой (ADR-0054 §6)."""
    versions = sorted(
        db.scalars(
            select(Price).where(Price.material_id == material_id, Price.supplier_id == supplier_id)
        ),
        key=_version_sort_key,
    )

    import_ids = {p.source_import_id for p in versions if p.source_import_id is not None}
    imports = (
        {
            i.id: i
            for i in db.scalars(select(PriceListImport).where(PriceListImport.id.in_(import_ids)))
        }
        if import_ids
        else {}
    )
    item_ids = {p.source_order_item_id for p in versions if p.source_order_item_id is not None}
    orders_by_item: dict[uuid.UUID, Order] = (
        {
            item_id: order
            for item_id, order in db.execute(
                select(OrderItem.id, Order)
                .join(Order, OrderItem.order_id == Order.id)
                .where(OrderItem.id.in_(item_ids))
            )
        }
        if item_ids
        else {}
    )
    user_ids = {p.created_by_user_id for p in versions if p.created_by_user_id is not None}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    )

    entries: list[PriceHistoryEntry] = []
    previous: Price | None = None
    for version in versions:
        source: Source
        if version.source_order_item_id is not None:
            source = "order"
        elif version.source_import_id is not None and (
            previous is None or previous.source_import_id != version.source_import_id
        ):
            source = "import"
        else:
            source = "manual"

        change: Change | None = None
        if previous is not None:
            change, _ = _classify(Decimal(version.price), previous)

        order = orders_by_item.get(version.source_order_item_id) if source == "order" else None
        import_ = imports.get(version.source_import_id) if source == "import" else None
        user = users.get(version.created_by_user_id) if version.created_by_user_id else None
        entries.append(
            PriceHistoryEntry(
                id=version.id,
                price=Decimal(version.price),
                currency=version.currency,
                valid_from=version.valid_from,
                valid_to=version.valid_to,
                source=source,
                import_id=import_.id if import_ is not None else None,
                import_uploaded_at=import_.uploaded_at if import_ is not None else None,
                order_id=order.id if order is not None else None,
                order_title=order.title if order is not None else None,
                created_by_name=(user.name or user.email) if user is not None else None,
                change=change,
            )
        )
        previous = version

    entries.reverse()
    return entries
