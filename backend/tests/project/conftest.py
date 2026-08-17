import uuid

import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Material, Project, ProjectItem


@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, project_ids, material_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
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
        session.commit()
        session.close()


@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids = db_session

    def _make(title="Test Project", created_by=None):
        project = Project(title=title, created_by=created_by)
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        return project

    return _make


@pytest.fixture
def make_material(db_session):
    session, _project_ids, material_ids = db_session

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
