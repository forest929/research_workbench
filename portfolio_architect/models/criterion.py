from enum import Enum
from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class CriterionType(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class CriterionResponse(BaseModel):
    id: UUID
    project_id: UUID
    workstream_run_id: UUID | None = None
    criterion_type: CriterionType
    statement: str
    rationale: str
    source_ids: list[str]
    confidence: float
    is_gold: bool
    gold_note: str | None = None
    gold_set_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CriterionPatch(BaseModel):
    is_gold: bool | None = None
    gold_note: str | None = None
    statement: str | None = None


class GoldLabelCreate(BaseModel):
    criterion_id: UUID | None = None
    text_sample: str
    label: Literal["inclusion", "exclusion", "ambiguous"]
    note: str | None = None
    is_hard_constraint: bool = True
    cluster_id: str | None = None
