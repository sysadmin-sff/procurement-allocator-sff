"""ILP-постановка подбора поставщика — реализация ADR-0002 через OR-Tools CP-SAT.

Модель строится только над M_solvable (материалы, прошедшие предобработку в
preprocess.split_orphaned_materials) — вызывающая сторона (service.py)
отвечает за то, чтобы AllocationInput.materials уже не содержал orphaned.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from app.allocation.types import (
    AllocationInput,
    AllocationLineResult,
    AllocationResult,
    SupplierSummary,
)

_STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}

STRICT_CATEGORIES = {"Doors", "Gutter", "Profil", "Mesh", "Roof panels"}
"""Категории, которые должны закупаться у одного поставщика в рамках проекта
(визуальная согласованность — двери/жёлоба/профили/экраны/кровельные панели
дают заметный на объекте цветовой разнобой между поставщиками). Реализовано
как soft-ограничение (штраф в целевой функции), не hard-constraint — см.
ADR-0028 §2: ни один поставщик не покрывает полный каталог ни одной строгой
категории, hard-ограничение резко повышало бы частоту INFEASIBLE. Сверено
буквально против CATEGORY_SKU_PREFIX реального импорта, см.
test_strict_categories_constant_matches_real_catalog (snapshot-тест)."""

CATEGORY_SPLIT_PENALTY_K = 4
"""Множитель к среднему flat_fee поставщиков проекта, дающий
category_split_penalty — см. ADR-0028 §2. Диапазон 3-5 предложен ADR, 4 взято
как стартовое значение; КАЛИБРУЕМАЯ константа — предмет донастройки после
наблюдения на реальных прогонах (ADR-0028 §2, "Точное значение k... не
фиксируется здесь как финальное число"), не финальное архитектурное решение."""


def solve_allocation(data: AllocationInput) -> AllocationResult:
    if not data.materials:
        return AllocationResult(status="NO_SOLVABLE_MATERIALS")

    qty = {m.material_id: m.quantity for m in data.materials}
    material_ids = list(qty.keys())

    # price[m][s], только для допустимых пар (Ограничение 2: недопустимые пары
    # исключаются из модели, а не запрещаются ограничением). availability=NULL
    # трактуется как "доступно" — см. ADR-0005; исключаем пару только когда
    # availability явно задан и его недостаточно.
    price: dict[tuple[str, str], int] = {}
    for p in data.prices:
        if p.material_id not in qty:
            continue
        if p.availability is not None and p.availability < qty[p.material_id]:
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

    # ADR-0028 §1/§2: diff[C][m] против опорного материала m* (min material_id
    # в категории) строгой категории — soft-механизм, только штраф в целевой
    # функции (§2), без hard-равенства x[m*][s] == x[m][s]. §3 требует, чтобы
    # категорийная группировка сама по себе не могла сделать модель
    # infeasible ("diff[C][m] — обычная бинарная переменная без принудительного
    # = 0") — hard-версия §1 (буквальный model.add(x[m*][s] == x[m][s])/== 0)
    # прямо противоречила бы этому и ключевому тесту "ни один поставщик не
    # покрывает всю категорию — soft-режим должен вернуть OPTIMAL/FEASIBLE, не
    # INFEASIBLE" (см. обсуждение при реализации — только diff-неравенства,
    # без hard-линковки). M_C — материалы категории, уже прошедшие
    # предобработку orphaned (уже в material_ids/x на этом этапе, ADR-0028 не
    # переоткрывает ADR-0002).
    category_map = {m.material_id: m.category for m in data.materials}
    materials_by_category: dict[str, list[str]] = {}
    for m_id in material_ids:
        cat = category_map.get(m_id)
        if cat in STRICT_CATEGORIES:
            materials_by_category.setdefault(cat, []).append(m_id)

    diff: dict[tuple[str, str], cp_model.IntVar] = {}  # (category, m_id) -> diff[C][m]
    for cat, cat_material_ids in materials_by_category.items():
        if len(cat_material_ids) < 2:
            continue
        ref_m_id = min(cat_material_ids)
        for m_id in cat_material_ids:
            if m_id == ref_m_id:
                continue
            diff_var = model.new_bool_var(f"diff_{cat}_{m_id}")
            diff[(cat, m_id)] = diff_var
            for s_id in supplier_ids:
                ref_var = x.get((ref_m_id, s_id))
                m_var = x.get((m_id, s_id))
                if ref_var is not None and m_var is not None:
                    model.add(diff_var >= ref_var - m_var)
                    model.add(diff_var >= m_var - ref_var)
                elif ref_var is not None:
                    model.add(diff_var >= ref_var)
                elif m_var is not None:
                    model.add(diff_var >= m_var)
                # else: обе переменные не существуют — вклад в diff по этому s
                # равен 0 константой, ничего не добавляем.

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

        if threshold is None:
            # Порог не настроен поставщиком — бесплатной доставки не бывает.
            model.add(free_var == 0)
        elif threshold == 0:
            # Порог явно выставлен в 0 — доставка бесплатна, как только поставщик задействован.
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

    # Целевая функция: цена + доставка (ADR-0002) + штраф за разброс строгой
    # категории (ADR-0028 §2). category_split_penalty масштабируется от
    # среднего flat_fee поставщиков проекта, не абсолютной суммой — см.
    # CATEGORY_SPLIT_PENALTY_K.
    price_terms = [x[(m_id, s_id)] * price[(m_id, s_id)] * qty[m_id] for (m_id, s_id) in x]
    delivery_terms = [z[s_id] * suppliers_by_id[s_id].flat_fee_cents for s_id in supplier_ids]

    penalty_terms: list[cp_model.LinearExpr] = []
    if diff:
        avg_flat_fee_cents = sum(
            suppliers_by_id[s_id].flat_fee_cents for s_id in supplier_ids
        ) / len(supplier_ids)
        category_split_penalty = round(CATEGORY_SPLIT_PENALTY_K * avg_flat_fee_cents)
        penalty_terms = [category_split_penalty * diff_var for diff_var in diff.values()]

    model.minimize(sum(price_terms) + sum(delivery_terms) + sum(penalty_terms))

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

    # y[s]=1 не гарантирует, что поставщику реально что-то назначено: когда
    # поставщик не входит ни в одно допустимое (m, s), ничто в модели не
    # принуждает его y[s] к 0 (Ограничение 3 — это x[m][s] <= y[s], оно не
    # работает в обратную сторону), и CP-SAT волен оставить y[s]=1 просто
    # потому что целевой функции это безразлично. Единственный надёжный
    # признак активности поставщика — наличие у него назначенных строк.
    active_supplier_ids = {line.supplier_id for line in lines}

    total_cents = sum(line.line_total_cents for line in lines) + sum(
        suppliers_by_id[s_id].flat_fee_cents
        for s_id in active_supplier_ids
        if not solver.value(free[s_id])
    )

    supplier_summaries: list[SupplierSummary] = []
    for s_id in sorted(active_supplier_ids):
        free_achieved = bool(solver.value(free[s_id]))
        supplier_summaries.append(
            SupplierSummary(
                supplier_id=s_id,
                goods_total_cents=solver.value(order_total[s_id]),
                delivery_fee_cents=0
                if free_achieved
                else suppliers_by_id[s_id].flat_fee_cents,
                free_shipping_achieved=free_achieved,
            )
        )

    return AllocationResult(
        status=status,
        lines=lines,
        supplier_summaries=supplier_summaries,
        total_cents=total_cents,
    )
