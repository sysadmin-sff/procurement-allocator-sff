import datetime
import uuid

import pytest

from app.core.database import SessionLocal
from app.models import (
    AllocationLine,
    AllocationRun,
    Material,
    Price,
    Project,
    ProjectItem,
    Supplier,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []
    supplier_ids: list = []

    try:
        yield session, project_ids, material_ids, supplier_ids
    finally:
        session.rollback()
        for project_id in project_ids:
            run_ids = [
                r.id for r in session.query(AllocationRun).filter_by(project_id=project_id).all()
            ]
            if run_ids:
                session.query(AllocationLine).filter(
                    AllocationLine.allocation_run_id.in_(run_ids)
                ).delete(synchronize_session=False)
                session.query(AllocationRun).filter(AllocationRun.id.in_(run_ids)).delete(
                    synchronize_session=False
                )
            session.query(ProjectItem).filter_by(project_id=project_id).delete(
                synchronize_session=False
            )
            session.query(Project).filter_by(id=project_id).delete(synchronize_session=False)
        if material_ids:
            session.query(Price).filter(Price.material_id.in_(material_ids)).delete(
                synchronize_session=False
            )
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
            session.query(Price).filter(Price.supplier_id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()


@pytest.fixture
def make_supplier(db_session):
    session, _project_ids, _material_ids, supplier_ids = db_session

    def _make(
        name="Test Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=0.0,
    ):
        supplier = Supplier(
            name=name,
            currency="USD",
            delivery_policy={
                "flat_fee": flat_fee,
                "free_shipping_threshold": free_shipping_threshold,
                "per_order_min_amount": per_order_min_amount,
                "lead_time_days": 1,
            },
        )
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_material(db_session):
    session, _project_ids, material_ids, _supplier_ids = db_session
    counter = {"n": 0}

    def _make(sku=None, unit="ft"):
        counter["n"] += 1
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=sku,
            unit=unit,
            attributes={},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


@pytest.fixture
def make_price(db_session):
    session, *_ = db_session

    def _make(material, supplier, price, availability=100, min_order_qty=1):
        p = Price(
            material=material,
            supplier=supplier,
            price=price,
            currency="USD",
            availability=availability,
            min_order_qty=min_order_qty,
            valid_from=datetime.date.today(),
            valid_to=None,
        )
        session.add(p)
        session.flush()
        return p

    return _make


@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids, _supplier_ids = db_session

    def _make(items):
        """items: list of (material, quantity) tuples."""
        project = Project(title="Test Project", status="draft")
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        for material, quantity in items:
            session.add(
                ProjectItem(project_id=project.id, material_id=material.id, quantity=quantity)
            )
        session.flush()
        return project

    return _make
