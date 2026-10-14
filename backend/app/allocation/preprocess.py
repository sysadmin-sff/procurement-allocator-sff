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
        # ADR-0045: сравниваем с order_qty этой конкретной пары (max(потребность,
        # min_order_qty)), не с исходной потребностью material.quantity --
        # поставщик с MOQ выше того, что у него физически есть в наличии, не
        # должен считаться достаточным просто потому что наличие покрывает
        # исходную (меньшую) потребность.
        has_sufficient = any(
            price.availability is None
            or price.availability >= max(material.quantity, price.min_order_qty)
            for price in candidate_prices
        )
        if has_sufficient:
            solvable.append(material)
            continue

        best_partial = _best_partial_offer(candidate_prices)
        # ADR-0045: если best_partial.availability фактически покрывает
        # required_quantity, но материал всё равно orphaned, причина --
        # MOQ этого offer (availability < order_qty, но >= required_quantity).
        # Без этого поля сообщение "требуется 37 -- частично доступно 50"
        # выглядело бы самопротиворечивым.
        blocking_moq = None
        if (
            best_partial is not None
            and best_partial.availability is not None
            and best_partial.availability >= material.quantity
        ):
            blocking_moq = best_partial.min_order_qty

        orphaned.append(
            OrphanedMaterial(
                material_id=material.material_id,
                required_quantity=material.quantity,
                best_partial_supplier_id=best_partial.supplier_id if best_partial else None,
                best_partial_available=best_partial.availability if best_partial else None,
                best_partial_min_order_qty=blocking_moq,
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
