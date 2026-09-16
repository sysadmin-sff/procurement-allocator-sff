"""Pure data types for the allocation solver — no ORM, no DB session.

Money is expressed as integer cents throughout the solver boundary because
CP-SAT works over integers; converting once at the edges (Decimal <-> cents)
keeps the model itself exact and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MaterialInput:
    material_id: str
    quantity: int
    category_id: str | None = None
    """Grouping key for ADR-0028 strict-category linking -- stable across a
    Category rename (FK id, not name). None only for materials somehow
    without a category (shouldn't occur after ADR-0034's NOT NULL, kept
    optional here because callers like preprocess.py don't care about
    category at all)."""
    requires_single_supplier: bool = False
    """Category.requires_single_supplier -- the only thing the solver needs
    to decide whether to group this material's category. See ADR-0034 §3."""
    category_name: str | None = None
    """Display-only -- used for split_categories text, never for grouping
    logic (category_id is the grouping key). See ADR-0034 §3."""


@dataclass(frozen=True)
class SupplierInput:
    supplier_id: str
    flat_fee_cents: int
    free_shipping_threshold_cents: int | None
    """None = порог не настроен поставщиком -> доставка никогда не бесплатна.
    0 = поставщик явно настроен на бесплатную доставку всегда (см. ADR-0002)."""
    per_order_min_amount_cents: int = 0


@dataclass(frozen=True)
class PriceInput:
    material_id: str
    supplier_id: str
    unit_price_cents: int
    availability: int | None


@dataclass(frozen=True)
class AllocationInput:
    materials: list[MaterialInput]
    suppliers: list[SupplierInput]
    prices: list[PriceInput]


@dataclass(frozen=True)
class OrphanedMaterial:
    material_id: str
    required_quantity: int
    best_partial_supplier_id: str | None = None
    best_partial_available: int | None = None


@dataclass(frozen=True)
class AllocationLineResult:
    material_id: str
    supplier_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


@dataclass(frozen=True)
class SupplierSummary:
    """Сводка по одному задействованному поставщику (y[s]=1) — экспортирует
    наружу order_total[s] и free[s] из ADR-0002, которые solve_allocation
    иначе считает только внутри модели и не возвращает."""

    supplier_id: str
    goods_total_cents: int
    delivery_fee_cents: int
    free_shipping_achieved: bool


@dataclass(frozen=True)
class AllocationResult:
    status: str  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "NO_SOLVABLE_MATERIALS"
    lines: list[AllocationLineResult] = field(default_factory=list)
    orphaned_materials: list[OrphanedMaterial] = field(default_factory=list)
    total_cents: int = 0
    supplier_summaries: list[SupplierSummary] = field(default_factory=list)
    """Kept as the last field deliberately — every construction site in this
    codebase uses keyword args already (verified, no positional calls exist),
    but a future positional call would silently mismatch types if this field
    weren't last. See docs/known-issues.md."""
