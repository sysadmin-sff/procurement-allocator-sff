import uuid
import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import (
    Material,
    Project,
    ProjectItem,
    ProjectTemplate,
    ProjectTemplateItem,
    User,
    UserSession,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    material_ids: list = []
    template_ids: list = []
    project_ids: list = []
    user_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, template_ids, project_ids, user_ids
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
        if template_ids:
            session.query(ProjectTemplateItem).filter(
                ProjectTemplateItem.template_id.in_(template_ids)
            ).delete(synchronize_session=False)
            session.query(ProjectTemplate).filter(
                ProjectTemplate.id.in_(template_ids)
            ).delete(synchronize_session=False)
        if material_ids:
            session.query(ProjectTemplateItem).filter(
                ProjectTemplateItem.material_id.in_(material_ids)
            ).delete(synchronize_session=False)
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_user(db_session):
    session, *_rest, user_ids = db_session

    def _make(
        email="employee@screen-factory-florida.com",
        google_sub=None,
        role="employee",
        is_active=True,
        name="Test User",
    ):
        user = User(email=email, google_sub=google_sub, role=role, is_active=is_active, name=name)
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    session, *_ = db_session

    def _make(user, csrf_token="test-csrf-token"):
        now = datetime.now(timezone.utc)
        user_session = UserSession(
            id=_uuid.uuid4(),
            user_id=user.id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=now + SESSION_IDLE_TTL,
            last_seen_at=now,
        )
        session.add(user_session)
        session.flush()
        return user_session

    return _make


@pytest.fixture
def make_material(db_session):
    session, material_ids, *_rest = db_session

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
def make_template(db_session):
    session, _material_ids, template_ids, _project_ids, _user_ids = db_session

    def _make(name=None, materials=None):
        """materials: optional list of Material added as ProjectTemplateItem rows."""
        name = name or f"Test Template {uuid.uuid4().hex[:8]}"
        template = ProjectTemplate(name=name)
        session.add(template)
        session.flush()
        template_ids.append(template.id)
        for material in materials or []:
            session.add(
                ProjectTemplateItem(template_id=template.id, material_id=material.id)
            )
        session.flush()
        session.refresh(template)
        return template

    return _make
