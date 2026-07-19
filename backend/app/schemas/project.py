from __future__ import annotations
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class ProjectCreate(BaseModel):
    """ Shared fields use by Create and Update. """
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    classification: str = "open"
    preferred_model: str | None = None

class ProjectUpdate(BaseModel):
    """POST /api/v1/projects body. Client only sets these. """
    name: str | None = None
    description: str | None = None
    status: str | None = None
    preferred_model: str | None = None

class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    owner_id: UUID
    status: str
    classification: str
    embed_model: str
    embed_dim: int
    preferred_model: str
    created_at: datetime
    created_by: UUID
