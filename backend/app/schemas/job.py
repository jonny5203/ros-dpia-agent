from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None
    kind: str
    status: str
    progress_pct: int
    error: str | None
    arq_job_id: str | None
    created_at: datetime
    updated_at: datetime
