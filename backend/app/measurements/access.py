from fastapi import Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.models import User


def require_measurements_access(user: User = Depends(get_current_user)) -> User:
    """Admin only (ADR-0055). Grants in measurements_user_access (ADR-0051 §2)
    no longer open the module; the table and scripts.grant_access stay
    untouched so the decision can be reverted without a migration."""
    has_access = user.role == "admin"
    if not user.is_active or not has_access:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user
