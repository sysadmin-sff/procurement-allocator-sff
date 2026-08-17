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


@dataclass(frozen=True)
class SupplierInput:
    supplier_id: str
    flat_fee_cents: int
    free_shipping_threshold_cents: int
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
class AllocationResult:
    status: str  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "NO_SOLVABLE_MATERIALS"
    lines: list[AllocationLineResult] = field(default_factory=list)
    orphaned_materials: list[OrphanedMaterial] = field(default_factory=list)
    total_cents: int = 0
