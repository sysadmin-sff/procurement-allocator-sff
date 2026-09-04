"""Single source of truth for sales-tax calculation — see ADR-0029.

Deliberately not part of solve_allocation()'s objective function: at a flat,
supplier-independent rate, tax is a constant multiplier on the price term and
cannot change which x[m][s] the solver picks as optimal — see ADR-0029
"Контекст" for the full argument and the condition under which that stops
being true (a rate that varies by supplier/state).
"""

from __future__ import annotations

TAX_RATE = 0.07
"""Sales tax (Florida), confirmed on a call with leadership and against a
real supplier invoice (2026-09-05). Does NOT vary by supplier/state in this
implementation — see ADR-0029 §2, an open question requiring business
confirmation, not decided either way."""


def calculate_tax(goods_subtotal_cents: int) -> int:
    """7% of the goods subtotal, rounded to the nearest cent — see ADR-0029
    §3. Must be called once on an already-summed subtotal, never per line
    and then summed (per-line rounding accumulates error). Never applied to
    delivery — goods_subtotal_cents must not include delivery_fee, the
    caller's responsibility."""
    return round(goods_subtotal_cents * TAX_RATE)


def calculate_tax_dollars(goods_subtotal: float) -> float:
    """Thin dollar wrapper for call sites not yet converted to cents
    (order_service.py) — delegates to calculate_tax, does not duplicate the
    `* TAX_RATE` formula. See ADR-0029 §1."""
    return calculate_tax(round(goods_subtotal * 100)) / 100
