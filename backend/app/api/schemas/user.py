import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    role: Literal["admin", "employee"]
    is_active: bool = True


class UserUpdate(BaseModel):
    role: Literal["admin", "employee"] | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}
