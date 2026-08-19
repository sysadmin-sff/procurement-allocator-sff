import uuid

import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import AllocationRun, Material, Order, Project, ProjectItem, Supplier


@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []
    supplier_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, project_ids, material_ids, supplier_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        for project_id in project_ids:
            order_ids = [
                o.id for o in session.query(Order).filter_by(project_id=project_id).all()
            ]
            if order_ids:
                session.query(Order).filter(Order.id.in_(order_ids)).delete(
                    synchronize_session=False
                )
            run_ids = [
                r.id
                for r in session.query(AllocationRun).filter_by(project_id=project_id).all()
            ]
            if run_ids:
                session.query(AllocationRun).filter(AllocationRun.id.in_(run_ids)).delete(
                    synchronize_session=False
                )
        if project_ids:
            session.query(ProjectItem).filter(
                ProjectItem.project_id.in_(project_ids)
            ).delete(synchronize_session=False)
            session.query(Project).filter(Project.id.in_(project_ids)).delete(
                synchronize_session=False
            )
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()


@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids, _supplier_ids = db_session

    def _make(title="Test Project", created_by=None, status="draft"):
        project = Project(title=title, created_by=created_by, status=status)
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        return project

    return _make


@pytest.fixture
def make_material(db_session):
    session, _project_ids, material_ids, _supplier_ids = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="ft"):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku, canonical_name=canonical_name or sku, category=category, unit=unit
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


@pytest.fixture
def make_supplier(db_session):
    session, _project_ids, _material_ids, supplier_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make
