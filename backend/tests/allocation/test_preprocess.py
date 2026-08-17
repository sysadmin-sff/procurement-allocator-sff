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


def test_material_with_null_availability_price_does_not_satisfy_and_is_not_partial():
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=500, availability=None)
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert orphaned[0].best_partial_supplier_id is None


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
