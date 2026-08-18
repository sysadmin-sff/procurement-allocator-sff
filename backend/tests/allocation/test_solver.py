from app.allocation.solver import solve_allocation
from app.allocation.types import AllocationInput, MaterialInput, PriceInput, SupplierInput


def test_material_with_null_availability_is_still_assignable():
    """See ADR-0005: availability=NULL means "not tracked", not "unavailable" —
    the pair (m, s) stays eligible for the solver, it isn't excluded."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None)
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=None)
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.lines) == 1
    assert result.lines[0].supplier_id == "s1"


def test_supplier_summary_reports_goods_total_and_no_free_shipping():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=1000,
            free_shipping_threshold_cents=100_000,
        )
    ]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert len(result.supplier_summaries) == 1
    summary = result.supplier_summaries[0]
    assert summary.supplier_id == "s1"
    assert summary.goods_total_cents == 500
    assert summary.delivery_fee_cents == 1000
    assert summary.free_shipping_achieved is False


def test_supplier_summary_reports_free_shipping_achieved():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=1000,
            free_shipping_threshold_cents=500,
        )
    ]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    summary = result.supplier_summaries[0]
    assert summary.goods_total_cents == 500
    assert summary.delivery_fee_cents == 0
    assert summary.free_shipping_achieved is True


def test_supplier_with_unset_threshold_never_gets_free_shipping():
    """free_shipping_threshold_cents=None (порог не настроен поставщиком) должен
    вести себя иначе, чем 0 (поставщик явно настроен на бесплатную доставку
    всегда) — задействованный поставщик без настроенного порога всегда платит
    flat_fee, независимо от суммы заказа."""
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=1000,
            free_shipping_threshold_cents=None,
        )
    ]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    summary = result.supplier_summaries[0]
    assert summary.delivery_fee_cents == 1000
    assert summary.free_shipping_achieved is False


def test_supplier_summary_excludes_unused_suppliers():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=0),
        SupplierInput(supplier_id="s2", flat_fee_cents=0, free_shipping_threshold_cents=0),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10),
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=900, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert len(result.supplier_summaries) == 1
    assert result.supplier_summaries[0].supplier_id == "s1"


def test_supplier_summary_covers_every_active_supplier_across_multiple():
    materials = [
        MaterialInput(material_id="m1", quantity=1),
        MaterialInput(material_id="m2", quantity=1),
    ]
    suppliers = [
        SupplierInput(
            supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=1500
        ),
        SupplierInput(
            supplier_id="s2", flat_fee_cents=1000, free_shipping_threshold_cents=100_000
        ),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=1000, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=600, availability=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=400, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    # This is the same consolidation scenario as
    # test_delivery_consolidation_is_preferred_over_cheapest_per_line_price:
    # both materials end up on s1, crossing its free-shipping threshold.
    assert len(result.supplier_summaries) == 1
    summary = result.supplier_summaries[0]
    assert summary.supplier_id == "s1"
    assert summary.goods_total_cents == 1600
    assert summary.delivery_fee_cents == 0
    assert summary.free_shipping_achieved is True


def test_single_material_single_supplier_is_assigned():
    materials = [MaterialInput(material_id="m1", quantity=10)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
        )
    ]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assert len(result.lines) == 1
    line = result.lines[0]
    assert line.material_id == "m1"
    assert line.supplier_id == "s1"
    assert line.quantity == 10
    assert line.unit_price_cents == 500
    assert line.line_total_cents == 5000


def test_supplier_below_free_shipping_threshold_pays_flat_fee():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=1000,
            free_shipping_threshold_cents=100_000,
        )
    ]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assert result.total_cents == 500 + 1000


def test_supplier_at_or_above_free_shipping_threshold_pays_no_fee():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=1000,
            free_shipping_threshold_cents=500,
        )
    ]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assert result.total_cents == 500


def test_delivery_consolidation_is_preferred_over_cheapest_per_line_price():
    # s1 is cheaper per-unit for both materials individually is not the case here:
    # s1 is cheapest for m1, s2 is cheapest for m2, but splitting across suppliers
    # means paying two flat fees. Consolidating onto s1 (crossing its free-shipping
    # threshold) beats paying s2's flat fee for a single cheap line.
    materials = [
        MaterialInput(material_id="m1", quantity=1),
        MaterialInput(material_id="m2", quantity=1),
    ]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=0,
            free_shipping_threshold_cents=1500,
        ),
        SupplierInput(
            supplier_id="s2",
            flat_fee_cents=1000,
            free_shipping_threshold_cents=100_000,
        ),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=1000, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=600, availability=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=400, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    # All on s1: 1000 + 600 = 1600, crosses 1500 threshold -> free shipping = 1600.
    # Split m1->s1, m2->s2: 1000 + 400 + 1000 (flat fee, below s2 threshold) = 2400.
    assert result.total_cents == 1600
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"m1": "s1", "m2": "s1"}


def test_delivery_consolidation_matches_seed_screen_room_scenario():
    # Regression pinned to the exact seed.py numbers (app/scripts/seed.py) for
    # the "Test Project — Screen Room 20x12" project: SCR-FG-96 is cheapest at
    # Alutex ($1.85) and AL-CH-EAVE is cheapest at Florida ($3.20), but
    # consolidating both onto Gulf Coast Screen Wholesale ($1.92 + $3.30)
    # crosses its $250 free-shipping threshold and drops its $45 flat fee,
    # which beats taking each material at its individually cheapest price and
    # paying delivery separately. AL-SMB-22W has no Gulf Coast price at all,
    # so it must go to Florida regardless. This is the scenario verified live
    # against the real seeded DB/HTTP endpoint -- pinned here so a future
    # seed.py price/threshold edit can't silently break it.
    materials = [
        MaterialInput(material_id="SCR-FG-96", quantity=120),
        MaterialInput(material_id="AL-SMB-22W", quantity=8),
        MaterialInput(material_id="AL-CH-EAVE", quantity=20),
    ]
    suppliers = [
        SupplierInput(
            supplier_id="Alutex",
            flat_fee_cents=6500,
            free_shipping_threshold_cents=150_000,
            per_order_min_amount_cents=20_000,
        ),
        SupplierInput(
            supplier_id="GulfCoast",
            flat_fee_cents=4500,
            free_shipping_threshold_cents=25_000,
            per_order_min_amount_cents=15_000,
        ),
        SupplierInput(
            supplier_id="Florida",
            flat_fee_cents=5500,
            free_shipping_threshold_cents=120_000,
            per_order_min_amount_cents=0,
        ),
    ]
    prices = [
        PriceInput(
            material_id="SCR-FG-96", supplier_id="Alutex", unit_price_cents=185, availability=4000
        ),
        PriceInput(
            material_id="SCR-FG-96",
            supplier_id="GulfCoast",
            unit_price_cents=192,
            availability=2500,
        ),
        PriceInput(
            material_id="AL-SMB-22W",
            supplier_id="Florida",
            unit_price_cents=410,
            availability=900,
        ),
        PriceInput(
            material_id="AL-SMB-22W", supplier_id="Alutex", unit_price_cents=435, availability=600
        ),
        PriceInput(
            material_id="AL-CH-EAVE",
            supplier_id="Florida",
            unit_price_cents=320,
            availability=1000,
        ),
        PriceInput(
            material_id="AL-CH-EAVE",
            supplier_id="GulfCoast",
            unit_price_cents=330,
            availability=150,
        ),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {
        "SCR-FG-96": "GulfCoast",
        "AL-SMB-22W": "Florida",
        "AL-CH-EAVE": "GulfCoast",
    }
    assert result.total_cents == 23040 + 3280 + 6600 + 5500  # goods + Florida's flat fee only

    summaries = {s.supplier_id: s for s in result.supplier_summaries}
    assert set(summaries) == {"GulfCoast", "Florida"}
    assert summaries["GulfCoast"].goods_total_cents == 23040 + 6600
    assert summaries["GulfCoast"].delivery_fee_cents == 0
    assert summaries["GulfCoast"].free_shipping_achieved is True
    assert summaries["Florida"].goods_total_cents == 3280
    assert summaries["Florida"].delivery_fee_cents == 5500
    assert summaries["Florida"].free_shipping_achieved is False


def test_per_order_min_amount_forces_larger_order_or_alternative_supplier():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
            per_order_min_amount_cents=10_000,
        ),
        SupplierInput(
            supplier_id="s2",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
        ),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=100, availability=10),
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=200, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    # s1 is cheaper but a single unit can't meet its $100 minimum order amount,
    # so the solver must route to s2 instead of leaving s1 active but under-minimum.
    assert result.status == "OPTIMAL"
    assert result.lines[0].supplier_id == "s2"


def test_min_order_amount_met_only_by_consolidating_multiple_materials():
    # m1 is only available at s1 ($8). m2 is cheaper at s2 ($5) than at s1
    # ($9). Without s1's minimum, the optimum would split: m1->s1 ($8),
    # m2->s2 ($5) = $13 total. But s1 has a $15 minimum order amount, and a
    # lone m1 order ($8) doesn't clear it -- s1 can only be used at all if m2
    # is consolidated onto it too ($8+$9=$17, clears $15). That's cheaper
    # than moving m2's business away and paying s1 nothing while m1 sits
    # unfulfilled -- s1 is m1's only source, so the solver must consolidate
    # both materials onto s1 to satisfy the minimum, not split them.
    materials = [
        MaterialInput(material_id="m1", quantity=1),
        MaterialInput(material_id="m2", quantity=1),
    ]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
            per_order_min_amount_cents=1_500,
        ),
        SupplierInput(
            supplier_id="s2",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
        ),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=800, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=900, availability=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=500, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.supplier_id for line in result.lines}
    assert assignments == {"s1"}
    assert result.total_cents == 800 + 900


def test_min_order_amount_infeasible_alone_falls_back_when_consolidation_not_enough():
    # Consolidating m1+m2 on s1 still only reaches $10 ($5+$5), below s1's $15
    # minimum -- the minimum is unreachable for this project even with full
    # consolidation, so the solver must route everything to s2 instead of
    # leaving s1 active with an under-minimum order.
    materials = [
        MaterialInput(material_id="m1", quantity=1),
        MaterialInput(material_id="m2", quantity=1),
    ]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
            per_order_min_amount_cents=1_500,
        ),
        SupplierInput(
            supplier_id="s2",
            flat_fee_cents=0,
            free_shipping_threshold_cents=0,
        ),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=500, availability=10),
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=1_200, availability=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=1_200, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.supplier_id for line in result.lines}
    assert assignments == {"s2"}


def test_big_m_must_not_understate_unreachable_threshold():
    # Regression for ADR-0002's own worked example: threshold $100 ($10000c),
    # max achievable order for this supplier is $20 ($2000c). M[s] must be
    # threshold + max_order_total, not just max_order_total, or the solver is
    # forced to set free[s]=1 even though the threshold is unreachable —
    # silently under-reporting delivery cost.
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1",
            flat_fee_cents=500,
            free_shipping_threshold_cents=10_000,
        )
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=2_000, availability=10)
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    # Threshold ($100) is unreachable (max order $20) -> flat fee must apply.
    assert result.total_cents == 2_000 + 500


def test_tied_price_between_two_suppliers_is_deterministic_across_runs():
    # Several materials, each priced identically at two fully symmetric
    # suppliers -- the ILP objective is indifferent between many equally
    # optimal assignments (any material can go to either supplier). A larger,
    # symmetric search space exercises the solver's internal tie-breaking far
    # more than a single-variable case would. The solver must still return
    # the exact same assignment on every run with identical input; a UI that
    # shows "why this supplier was chosen" cannot tolerate the answer
    # changing between an allocation run and a page refresh that recomputes it.
    materials = [MaterialInput(material_id=f"m{i}", quantity=1) for i in range(8)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=0),
        SupplierInput(supplier_id="s2", flat_fee_cents=0, free_shipping_threshold_cents=0),
    ]
    prices = [
        PriceInput(
            material_id=m.material_id, supplier_id=s_id, unit_price_cents=500, availability=10
        )
        for m in materials
        for s_id in ("s1", "s2")
    ]
    data = AllocationInput(materials=materials, suppliers=suppliers, prices=prices)

    results = [solve_allocation(data) for _ in range(20)]

    assert all(r.status == "OPTIMAL" for r in results)
    assignments = [
        tuple(sorted((line.material_id, line.supplier_id) for line in r.lines)) for r in results
    ]
    assert len(set(assignments)) == 1, (
        f"non-deterministic tie-break across runs: {set(assignments)}"
    )


def test_no_valid_supplier_for_any_material_is_infeasible():
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=0)]
    prices: list[PriceInput] = []

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status in ("INFEASIBLE", "MODEL_INVALID")
    assert result.lines == []


def test_multiple_materials_each_get_a_line():
    materials = [
        MaterialInput(material_id="m1", quantity=2),
        MaterialInput(material_id="m2", quantity=3),
    ]
    suppliers = [SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=0)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=100, availability=5),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=200, availability=5),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assert len(result.lines) == 2
    assert result.total_cents == 2 * 100 + 3 * 200
