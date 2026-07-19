from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime: str
    ext: str
    sha256: str
    classification: str
    processing_status: str
    uploaded_by: UUID
    uploaded_at: datetime
