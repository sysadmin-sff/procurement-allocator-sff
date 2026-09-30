"""widen money columns to 3 decimals

Raises Price.price, AllocationLine.unit_price/line_total/original_unit_price
and OrderItem.quoted_price/confirmed_price/received_price/target_price from
Numeric(12, 2) to Numeric(12, 3) -- price-list entries like "10 x 3/4"
Bronze/White Stainless steel" at $0.625/pcs need a 3rd decimal (per-unit
pricing on small hardware), and the frontend step="0.01" on the price input
was silently rejecting such values.

Does NOT touch the ILP solver boundary: app/allocation/service.py's
_to_cents()/_from_cents() still work in whole cents (_CENTS_PER_UNIT = 100,
see app/allocation/types.py's module docstring) because CP-SAT requires
integers. A price that goes through run_allocation() -> create_orders_for_run
is still rounded to 2 decimals at that boundary regardless of this column's
precision -- this migration only removes the DB-level truncation for the
paths that bypass the solver: manual price-list entry (Price.price); the
manual-override recompute of AllocationLine.unit_price/line_total against a
newly-selected Price (service.py:350, a direct multiply, not _to_cents);
and the values copied straight from Price.price without going through the
solver (find-replacement's candidate["price"] snapshot into
OrderItem.quoted_price, and OrderItem.confirmed_price/received_price/
target_price, all set directly by an employee via PATCH
.../items/{item_id}, never computed from cents). Widening the solver-path
writes themselves (AllocationLine.unit_price/line_total via
create_orders_for_run, OrderItem.quoted_price via the same) is for schema
consistency only, not because it changes what those particular writes can
now store.

Numeric(12,2) -> Numeric(12,3) is a widening, so downgrade is lossy (any
3rd-decimal digit written under the wider precision is truncated on
downgrade) -- acceptable, same one-way shape as f41d3f445189.

Revision ID: c7f2a91b4e0d
Revises: f41d3f445189
Create Date: 2026-10-01 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7f2a91b4e0d"
down_revision: str | None = "f41d3f445189"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    ("prices", "price"),
    ("allocation_lines", "unit_price"),
    ("allocation_lines", "line_total"),
    ("allocation_lines", "original_unit_price"),
    ("order_items", "quoted_price"),
    ("order_items", "confirmed_price"),
    ("order_items", "received_price"),
    ("order_items", "target_price"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, type_=sa.Numeric(12, 3))


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, type_=sa.Numeric(12, 2))
