import uuid

from pydantic import BaseModel


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str

    model_config = {"from_attributes": True}
