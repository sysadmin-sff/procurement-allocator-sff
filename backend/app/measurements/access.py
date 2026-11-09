from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.measurements.models import MeasurementsUserAccess
from app.models import User


def require_measurements_access(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """Third access category next to ADR-0024 §4 (ADR-0051 §2)."""
    has_access = user.role == "admin" or db.get(MeasurementsUserAccess, user.id) is not None
    if not user.is_active or not has_access:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
