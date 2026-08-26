import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.user import UserCreate, UserOut, UserUpdate
from app.auth.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.models import User

router = APIRouter(prefix="/users", dependencies=[Depends(require_role("admin"))])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.query(User).order_by(User.email).all())


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(
        email=payload.email, role=payload.role, is_active=payload.is_active, google_sub=None
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A user with this email already exists"
        ) from exc
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    deactivating_self = (
        payload.is_active is False and user.id == current_user.id and user.role == "admin"
    )
    if deactivating_self:
        other_active_admins = (
            db.query(User)
            .filter(User.role == "admin", User.is_active.is_(True), User.id != user.id)
            .first()
        )
        if other_active_admins is None:
            raise HTTPException(status_code=409, detail="Cannot deactivate the last active admin")

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return user
