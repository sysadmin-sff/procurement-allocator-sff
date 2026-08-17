"""Наполняет БД тестовыми поставщиками, материалами и ценами для локальной разработки."""

import datetime

from app.core.database import SessionLocal
from app.models import Material, Price, Supplier

SUPPLIERS = [
    {
        "name": "Alutex Supply Co.",
        "contacts": "orders@alutexsupply.com",
        "currency": "USD",
        "delivery_policy": {
            "flat_fee": 65.00,
            "free_shipping_threshold": 1500.00,
            "per_order_min_amount": 200.00,
            "lead_time_days": 3,
        },
    },
    {
        "name": "Gulf Coast Screen Wholesale",
        "contacts": "sales@gulfcoastscreen.com",
        "currency": "USD",
        "delivery_policy": {
            "flat_fee": 45.00,
            "free_shipping_threshold": 1000.00,
            "per_order_min_amount": 150.00,
            "lead_time_days": 2,
        },
    },
    {
        "name": "Phifer Direct",
        "contacts": "b2b@phiferdirect.com",
        "currency": "USD",
        "delivery_policy": {
            "flat_fee": 80.00,
            "free_shipping_threshold": 2000.00,
            "per_order_min_amount": 300.00,
            "lead_time_days": 5,
        },
    },
    {
        "name": "Florida Aluminum Distributors",
        "contacts": "orders@fladistributors.com",
        "currency": "USD",
        "delivery_policy": {
            "flat_fee": 55.00,
            "free_shipping_threshold": 1200.00,
            "per_order_min_amount": 0,
            "lead_time_days": 4,
        },
    },
]

MATERIALS = [
    {
        "internal_sku": "SCR-FG-96",
        "canonical_name": 'Fiberglass Screen 96"',
        "category": "screen",
        "unit": "ft",
        "attributes": {"width_in": 96, "material": "fiberglass"},
    },
    {
        "internal_sku": "SCR-SS-96",
        "canonical_name": 'Super Screen 96"',
        "category": "screen",
        "unit": "ft",
        "attributes": {"width_in": 96, "material": "polyester"},
    },
    {
        "internal_sku": "SCR-PET-72",
        "canonical_name": 'Pet Screen 72"',
        "category": "screen",
        "unit": "ft",
        "attributes": {"width_in": 72, "material": "vinyl-coated polyester"},
    },
    {
        "internal_sku": "AL-SMB-22W",
        "canonical_name": "Aluminum SMB Beam 22ft White",
        "category": "frame",
        "unit": "ft",
        "attributes": {"length_ft": 22, "color": "white"},
    },
    {
        "internal_sku": "AL-SMB-22B",
        "canonical_name": "Aluminum SMB Beam 22ft Bronze",
        "category": "frame",
        "unit": "ft",
        "attributes": {"length_ft": 22, "color": "bronze"},
    },
    {
        "internal_sku": "AL-CH-EAVE",
        "canonical_name": "Aluminum Eave Channel",
        "category": "frame",
        "unit": "ft",
        "attributes": {},
    },
    {
        "internal_sku": "SPL-BASE-2",
        "canonical_name": '2" Base Spline',
        "category": "spline",
        "unit": "roll",
        "attributes": {"diameter_in": 0.2},
    },
    {
        "internal_sku": "SPL-BASE-175",
        "canonical_name": '.175" Base Spline',
        "category": "spline",
        "unit": "roll",
        "attributes": {"diameter_in": 0.175},
    },
    {
        "internal_sku": "FSTN-SMS-8",
        "canonical_name": '#8 Self-Tapping Screw 1"',
        "category": "fastener",
        "unit": "box",
        "attributes": {"size": "#8", "length_in": 1},
    },
    {
        "internal_sku": "FSTN-RIVET-1/8",
        "canonical_name": '1/8" Aluminum Rivet',
        "category": "fastener",
        "unit": "box",
        "attributes": {"diameter_in": 0.125},
    },
    {
        "internal_sku": "HW-HINGE-SS",
        "canonical_name": "Stainless Door Hinge",
        "category": "hardware",
        "unit": "pcs",
        "attributes": {"material": "stainless steel"},
    },
    {
        "internal_sku": "HW-LATCH-STD",
        "canonical_name": "Standard Door Latch",
        "category": "hardware",
        "unit": "pcs",
        "attributes": {},
    },
    {
        "internal_sku": "SLNT-CLR-10",
        "canonical_name": "Clear Silicone Sealant 10oz",
        "category": "sealant",
        "unit": "tube",
        "attributes": {"volume_oz": 10},
    },
    {
        "internal_sku": "AL-CH-GUTTER",
        "canonical_name": "Aluminum Gutter Channel",
        "category": "frame",
        "unit": "ft",
        "attributes": {},
    },
    {
        "internal_sku": "SCR-FG-84",
        "canonical_name": 'Fiberglass Screen 84"',
        "category": "screen",
        "unit": "ft",
        "attributes": {"width_in": 84, "material": "fiberglass"},
    },
]

# (material_sku, supplier_name, price, availability, min_order_qty)
PRICES = [
    ("SCR-FG-96", "Alutex Supply Co.", 1.85, 4000, 100),
    ("SCR-FG-96", "Gulf Coast Screen Wholesale", 1.92, 2500, 50),
    ("SCR-SS-96", "Alutex Supply Co.", 2.35, 1800, 100),
    ("SCR-SS-96", "Phifer Direct", 2.20, 3000, 200),
    ("SCR-PET-72", "Gulf Coast Screen Wholesale", 1.55, 1200, 50),
    ("AL-SMB-22W", "Florida Aluminum Distributors", 4.10, 900, 22),
    ("AL-SMB-22W", "Alutex Supply Co.", 4.35, 600, 22),
    ("AL-SMB-22B", "Florida Aluminum Distributors", 4.60, 500, 22),
    ("AL-CH-EAVE", "Florida Aluminum Distributors", 3.20, 1000, 10),
    ("SPL-BASE-2", "Gulf Coast Screen Wholesale", 18.50, 150, 1),
    ("SPL-BASE-175", "Phifer Direct", 17.90, 180, 1),
    ("FSTN-SMS-8", "Alutex Supply Co.", 12.75, 300, 1),
    ("FSTN-RIVET-1/8", "Florida Aluminum Distributors", 9.40, 400, 1),
    ("HW-HINGE-SS", "Alutex Supply Co.", 6.80, 250, 1),
    ("HW-LATCH-STD", "Alutex Supply Co.", 5.25, 300, 1),
    ("SLNT-CLR-10", "Gulf Coast Screen Wholesale", 4.10, 500, 1),
    ("AL-CH-GUTTER", "Florida Aluminum Distributors", 3.85, 700, 10),
    ("SCR-FG-84", "Phifer Direct", 1.70, 2000, 100),
]


def seed() -> None:
    db = SessionLocal()
    try:
        suppliers_by_name: dict[str, Supplier] = {}
        for data in SUPPLIERS:
            supplier = db.query(Supplier).filter_by(name=data["name"]).one_or_none()
            if supplier is None:
                supplier = Supplier(**data)
                db.add(supplier)
            suppliers_by_name[data["name"]] = supplier

        materials_by_sku: dict[str, Material] = {}
        for data in MATERIALS:
            material = db.query(Material).filter_by(internal_sku=data["internal_sku"]).one_or_none()
            if material is None:
                material = Material(**data)
                db.add(material)
            materials_by_sku[data["internal_sku"]] = material

        db.flush()

        today = datetime.date.today()
        for sku, supplier_name, price, availability, min_order_qty in PRICES:
            material = materials_by_sku[sku]
            supplier = suppliers_by_name[supplier_name]
            existing = (
                db.query(Price)
                .filter_by(material_id=material.id, supplier_id=supplier.id, valid_to=None)
                .one_or_none()
            )
            if existing is not None:
                continue
            db.add(
                Price(
                    material=material,
                    supplier=supplier,
                    price=price,
                    currency="USD",
                    availability=availability,
                    min_order_qty=min_order_qty,
                    valid_from=today,
                    valid_to=None,
                )
            )

        db.commit()
        print(
            f"Seeded {len(SUPPLIERS)} suppliers, {len(MATERIALS)} materials, "
            f"{len(PRICES)} prices."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
