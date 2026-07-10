from enum import Enum
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class ProjectState(str, Enum):
    ONBOARDING = "onboarding"
    INGESTING = "ingesting"
    EMBEDDING = "embedding"
    ANALYZING = "analyzing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"
    DEATH_SPIRAL = "death_spiral"
    FAILED = "failed"


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    scope_statement: str


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str
    scope_statement: str
    state: ProjectState
    death_spiral_reason: str | None = None
    iteration_count: int
    created_at: datetime
    updated_at: datetime


class ProjectApproveRequest(BaseModel):
    pass


class ProjectResolveRequest(BaseModel):
    resolution_guidance: str
