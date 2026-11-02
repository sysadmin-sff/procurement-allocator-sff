"""Per-piece price for an order-response line — see ADR-0050.

The model only transcribes what the document prints (price, what it is
priced per, the priced quantity, the line amount, pieces); this module does
the arithmetic deterministically with Decimal, so a per-linear-foot quote
(Eastern Metal: 224 ft x $2.80 = $627.20 for 8 pcs) becomes $78.40/шт —
the scale our OrderItem.quoted_price is in. Never raises on odd input: when
the per-piece price can't be derived, the printed price is kept and the
line carries a warning for the review screen.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.order_response_parser.client import ExtractedLine, RawExtractedLine

_PRICE_STEP = Decimal("0.001")  # OrderItem prices are Numeric(12,3)
_CENT = Decimal("0.01")

_BASIS_LABEL = {"linear_foot": "погонный фут", "other": "единицу, отличную от штуки"}


def _d(value: float) -> Decimal:
    return Decimal(str(value))


def _money3(value: Decimal) -> str:
    return f"${value.quantize(_PRICE_STEP, rounding=ROUND_HALF_UP)}"


def _money2(value: Decimal) -> str:
    return f"${value.quantize(_CENT, rounding=ROUND_HALF_UP)}"


def _qty(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _mismatch_warning(total: Decimal, computed: Decimal) -> str:
    return (
        f"Сумма строки {_money2(total)} не сходится с ценой × количеством "
        f"({_money2(computed)}) — проверьте цену."
    )


def normalize_line(raw: RawExtractedLine) -> ExtractedLine:
    printed = _d(raw.printed_unit_price)
    total = _d(raw.line_total) if raw.line_total is not None else None
    priced_qty = _d(raw.priced_quantity) if raw.priced_quantity is not None else None
    pieces = Decimal(raw.quantity) if raw.quantity else None

    price = printed
    note: str | None = None
    warning: str | None = None

    if raw.price_basis == "piece":
        if total is not None and pieces is not None and abs(printed * pieces - total) > _CENT:
            warning = _mismatch_warning(total, printed * pieces)
    elif pieces is not None and (total is not None or priced_qty is not None):
        if total is not None:
            price = total / pieces
            if priced_qty is not None and abs(printed * priced_qty - total) > _CENT:
                warning = _mismatch_warning(total, printed * priced_qty)
        else:
            price = printed * priced_qty / pieces
        price = price.quantize(_PRICE_STEP, rounding=ROUND_HALF_UP)
        unit = "фут" if raw.price_basis == "linear_foot" else "ед."
        steps = [f"{_money3(printed)}/{unit}"]
        if priced_qty is not None:
            steps[0] += f" × {_qty(priced_qty)} {'фт' if unit == 'фут' else 'ед.'}"
        if total is not None:
            steps.append(_money2(total))
        note = " = ".join(steps) + f" ÷ {_qty(pieces)} шт = {_money3(price)}/шт"
    else:
        warning = (
            f"Цена указана за {_BASIS_LABEL[raw.price_basis]}, пересчитать в цену за "
            "штуку не удалось — проверьте цену."
        )

    return ExtractedLine(
        raw_description=raw.raw_description,
        matched_order_item_id=raw.matched_order_item_id,
        price=float(price),
        quantity=raw.quantity,
        confidence=raw.confidence,
        reasoning=raw.reasoning,
        price_note=note,
        price_warning=warning,
    )
