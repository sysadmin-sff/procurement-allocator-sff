"""Predобработка недостижимых материалов — ADR-0002, раздел
"Предобработка: недостижимые материалы (orphaned materials)".

availability = NULL трактуется как "доступно" (не как "недостаточно") —
см. ADR-0005: наличие подтверждается поставщиком только после отправки
ордера, на этапе расчёта оно обычно не заполнено.
"""

from __future__ import annotations

from app.allocation.types import MaterialInput, OrphanedMaterial, PriceInput


def split_orphaned_materials(
    materials: list[MaterialInput],
    prices: list[PriceInput],
) -> tuple[list[MaterialInput], list[OrphanedMaterial]]:
    prices_by_material: dict[str, list[PriceInput]] = {}
    for price in prices:
        prices_by_material.setdefault(price.material_id, []).append(price)

    solvable: list[MaterialInput] = []
    orphaned: list[OrphanedMaterial] = []

    for material in materials:
        candidate_prices = prices_by_material.get(material.material_id, [])
        has_sufficient = any(
            price.availability is None or price.availability >= material.quantity
            for price in candidate_prices
        )
        if has_sufficient:
            solvable.append(material)
            continue

        best_partial = _best_partial_offer(candidate_prices)
        orphaned.append(
            OrphanedMaterial(
                material_id=material.material_id,
                required_quantity=material.quantity,
                best_partial_supplier_id=best_partial.supplier_id if best_partial else None,
                best_partial_available=best_partial.availability if best_partial else None,
            )
        )

    return solvable, orphaned


def _best_partial_offer(prices: list[PriceInput]) -> PriceInput | None:
    partial_offers = [
        price for price in prices if price.availability is not None and price.availability > 0
    ]
    if not partial_offers:
        return None
    return max(partial_offers, key=lambda price: price.availability)
