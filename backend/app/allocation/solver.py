"""ILP-постановка подбора поставщика — реализация ADR-0002 через OR-Tools CP-SAT.

Модель строится только над M_solvable (материалы, прошедшие предобработку в
preprocess.split_orphaned_materials) — вызывающая сторона (service.py)
отвечает за то, чтобы AllocationInput.materials уже не содержал orphaned.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from app.allocation.types import AllocationInput, AllocationLineResult, AllocationResult

_STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


def solve_allocation(data: AllocationInput) -> AllocationResult:
    if not data.materials:
        return AllocationResult(status="NO_SOLVABLE_MATERIALS")

    qty = {m.material_id: m.quantity for m in data.materials}
    material_ids = list(qty.keys())

    # price[m][s], только для допустимых пар (Ограничение 2: недопустимые пары
    # исключаются из модели, а не запрещаются ограничением).
    price: dict[tuple[str, str], int] = {}
    for p in data.prices:
        if p.material_id not in qty:
            continue
        if p.availability is None or p.availability < qty[p.material_id]:
            continue
        price[(p.material_id, p.supplier_id)] = p.unit_price_cents

    suppliers_by_id = {s.supplier_id: s for s in data.suppliers}
    supplier_ids = sorted({s for (_, s) in price})

    model = cp_model.CpModel()

    # Переменные x[m][s].
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for m_id in material_ids:
        for s_id in supplier_ids:
            if (m_id, s_id) in price:
                x[(m_id, s_id)] = model.new_bool_var(f"x_{m_id}_{s_id}")

    # Ограничение 1: назначение — ровно один поставщик на материал.
    for m_id in material_ids:
        candidates = [x[(m_id, s_id)] for s_id in supplier_ids if (m_id, s_id) in x]
        model.add(sum(candidates) == 1)

    # Переменные y[s].
    y: dict[str, cp_model.IntVar] = {s_id: model.new_bool_var(f"y_{s_id}") for s_id in supplier_ids}

    # Ограничение 3: активация поставщика.
    for (_m_id, s_id), var in x.items():
        model.add(var <= y[s_id])

    # order_total[s] = Σ_m x[m][s] * price[m][s] * qty[m]
    order_total: dict[str, cp_model.LinearExpr] = {}
    max_order_total: dict[str, int] = {}
    for s_id in supplier_ids:
        terms = [
            x[(m_id, s_id)] * price[(m_id, s_id)] * qty[m_id]
            for m_id in material_ids
            if (m_id, s_id) in x
        ]
        order_total[s_id] = sum(terms)
        max_order_total[s_id] = sum(
            price[(m_id, s_id)] * qty[m_id] for m_id in material_ids if (m_id, s_id) in x
        )

    # Ограничение 4: минимальная сумма заказа (опционально).
    for s_id in supplier_ids:
        min_amount = suppliers_by_id[s_id].per_order_min_amount_cents
        if min_amount > 0:
            model.add(order_total[s_id] >= min_amount * y[s_id])

    # free[s] и big-M linking для free_shipping_threshold.
    free: dict[str, cp_model.IntVar] = {}
    z: dict[str, cp_model.IntVar] = {}
    epsilon_cents = 1
    for s_id in supplier_ids:
        threshold = suppliers_by_id[s_id].free_shipping_threshold_cents
        free_var = model.new_bool_var(f"free_{s_id}")
        free[s_id] = free_var

        if threshold <= 0:
            # Порог не задан/нулевой — доставка бесплатна, как только поставщик задействован.
            model.add(free_var == y[s_id])
        else:
            big_m = threshold + max_order_total[s_id]
            model.add(order_total[s_id] >= threshold - big_m * (1 - free_var))
            model.add(order_total[s_id] <= threshold - epsilon_cents + big_m * free_var)
            model.add(free_var <= y[s_id])

        # Линеаризация z[s] = y[s] * (1 - free[s]).
        z_var = model.new_bool_var(f"z_{s_id}")
        z[s_id] = z_var
        model.add(z_var <= y[s_id])
        model.add(z_var <= 1 - free_var)
        model.add(z_var >= y[s_id] - free_var)

    # Целевая функция.
    price_terms = [x[(m_id, s_id)] * price[(m_id, s_id)] * qty[m_id] for (m_id, s_id) in x]
    delivery_terms = [z[s_id] * suppliers_by_id[s_id].flat_fee_cents for s_id in supplier_ids]
    model.minimize(sum(price_terms) + sum(delivery_terms))

    solver = cp_model.CpSolver()
    # Фиксированный seed и однопоточный поиск — гарантия одинакового
    # tie-break между равнозначными по цене решениями на любом запуске,
    # а не полагание на поведение солвера по умолчанию (которое зависит
    # от числа ядер хоста при num_search_workers, не заданном явно).
    solver.parameters.random_seed = 1
    solver.parameters.num_search_workers = 1
    status_code = solver.solve(model)
    status = _STATUS_NAMES.get(status_code, "UNKNOWN")

    if status not in ("OPTIMAL", "FEASIBLE"):
        return AllocationResult(status=status)

    lines: list[AllocationLineResult] = []
    for (m_id, s_id), var in x.items():
        if solver.value(var):
            unit_price = price[(m_id, s_id)]
            quantity = qty[m_id]
            lines.append(
                AllocationLineResult(
                    material_id=m_id,
                    supplier_id=s_id,
                    quantity=quantity,
                    unit_price_cents=unit_price,
                    line_total_cents=unit_price * quantity,
                )
            )

    total_cents = sum(line.line_total_cents for line in lines) + sum(
        suppliers_by_id[s_id].flat_fee_cents
        for s_id in supplier_ids
        if solver.value(y[s_id]) and not solver.value(free[s_id])
    )

    return AllocationResult(status=status, lines=lines, total_cents=total_cents)
