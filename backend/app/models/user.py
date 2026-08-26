import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    google_sub: Mapped[str | None] = mapped_column(String(255))
    """NULL only for rows an admin pre-created by email before that person's
    first login — filled on first successful login and used as the primary
    lookup key thereafter (email can change in Workspace, sub cannot).
    Uniqueness enforced by the partial index `ix_users_google_sub`
    (`WHERE google_sub IS NOT NULL`) in the migration, not a column-level
    constraint — see ADR-0024 §2 and the users/user_sessions migration."""
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    """Uniqueness enforced by the `ix_users_email` index in the migration."""
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    """'admin' | 'employee'. See ADR-0024 §2."""
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(UUIDPKMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    csrf_token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")
