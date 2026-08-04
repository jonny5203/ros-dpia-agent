from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.ai.prompts.profile import OutputLanguage


class AnalysisRequest(BaseModel):
    output_language: OutputLanguage = "nb"


class AnalysisJobResponse(BaseModel):
    job_id: UUID
