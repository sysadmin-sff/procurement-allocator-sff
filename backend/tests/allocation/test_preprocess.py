from app.allocation.preprocess import split_orphaned_materials
from app.allocation.types import MaterialInput, PriceInput


def test_material_with_sufficient_price_is_solvable():
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10)]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == materials
    assert orphaned == []


def test_material_with_no_price_at_all_is_orphaned():
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices: list[PriceInput] = []

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert len(orphaned) == 1
    assert orphaned[0].material_id == "m1"
    assert orphaned[0].required_quantity == 10
    assert orphaned[0].best_partial_supplier_id is None
    assert orphaned[0].best_partial_available is None


def test_material_with_insufficient_availability_everywhere_is_orphaned_with_best_partial():
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=3),
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=600, availability=7),
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert len(orphaned) == 1
    assert orphaned[0].best_partial_supplier_id == "s2"
    assert orphaned[0].best_partial_available == 7


def test_material_with_zero_availability_offer_has_no_partial_suggestion():
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=0)]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert orphaned[0].best_partial_supplier_id is None
    assert orphaned[0].best_partial_available is None


def test_material_with_null_availability_price_is_treated_as_available():
    """availability = NULL means "not tracked", not "zero in stock" — see
    ADR-0005: suppliers only confirm real stock after an order is sent, so
    availability is routinely unset at calculation time."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=None)
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == materials
    assert orphaned == []


def test_material_solvable_via_null_availability_even_if_another_supplier_has_insufficient():
    """One offer with an explicit, insufficient availability shouldn't shadow
    a NULL offer from a different supplier — NULL still rescues the material."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=3),
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=600, availability=None),
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == materials
    assert orphaned == []


def test_mix_of_solvable_and_orphaned_materials_are_both_reported():
    materials = [
        MaterialInput(material_id="m1", quantity=10),
        MaterialInput(material_id="m2", quantity=5),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=200, availability=1),
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert [m.material_id for m in solvable] == ["m1"]
    assert [m.material_id for m in orphaned] == ["m2"]


def test_moq_availability_checked_against_order_qty_not_demand():
    """availability=50, min_order_qty=100 (потребность=37) -> order_qty=100
    -> материал должен попасть в orphaned, хотя по "наивному" сравнению с
    потребностью (37) availability казалось бы достаточным. Прямая
    регрессия против упущения первой версии ADR-0045 (см. §Контекст)."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=50, min_order_qty=100,
        )
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert len(orphaned) == 1
    assert orphaned[0].material_id == "m1"
    assert orphaned[0].required_quantity == 37


def test_moq_all_suppliers_insufficient_availability_material_orphaned():
    """Ни у одного поставщика материала availability >= order_qty ->
    материал в orphaned."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=5, min_order_qty=50,
        ),
        PriceInput(
            material_id="m1", supplier_id="s2", unit_price_cents=120,
            availability=3, min_order_qty=50,
        ),
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert len(orphaned) == 1
    assert orphaned[0].best_partial_supplier_id == "s1"
    assert orphaned[0].best_partial_available == 5


def test_moq_orphaned_best_partial_offer_records_blocking_moq():
    """availability=50 covers the raw demand (37) but not order_qty (100,
    from MOQ=100) -- the message "требуется 37 -- частично доступно 50"
    would be self-contradictory (50 > 37) without knowing MOQ is the real
    reason the offer doesn't qualify. best_partial_min_order_qty must
    carry that MOQ so the UI can explain it."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=50, min_order_qty=100,
        )
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert orphaned[0].best_partial_supplier_id == "s1"
    assert orphaned[0].best_partial_available == 50
    assert orphaned[0].best_partial_min_order_qty == 100


def test_moq_orphaned_best_partial_offer_min_order_qty_null_when_not_the_cause():
    """Ordinary stock shortfall (no MOQ involved, or MOQ not the binding
    constraint) must leave best_partial_min_order_qty as NULL -- not every
    orphaned material is caused by MOQ."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=100, availability=3)
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert orphaned[0].best_partial_min_order_qty is None


def test_moq_sufficient_availability_against_order_qty_keeps_material_solvable():
    """availability >= order_qty (не только >= потребности) -> материал
    остаётся решаемым, как и раньше в обычном случае без MOQ."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=150, min_order_qty=100,
        )
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert len(solvable) == 1
    assert orphaned == []
