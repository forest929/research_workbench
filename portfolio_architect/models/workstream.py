from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

from .criterion import CriterionResponse
from .judge import JudgeVerdict


class WorkstreamRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    run_id: UUID
    workstream: Literal["literature_synthesis", "parameter_extraction", "cluster_selection"]
    status: Literal["pending", "running", "complete", "failed"]
    result_summary: str | None = None
    error_msg: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResearchRunResponse(BaseModel):
    project_id: UUID
    run_id: UUID
    workstream_runs: list[WorkstreamRunResponse]
    judge_verdict: JudgeVerdict | None = None
    criteria_extracted: list[CriterionResponse]
    state_after: str
    death_spiral_reason: str | None = None


class DiscrepancyRequest(BaseModel):
    definition_a: str
    definition_b: str
    label_a: str = "Team A"
    label_b: str = "Team B"


class FrictionPoint(BaseModel):
    summary: str
    position_a: str
    position_b: str
    friction_type: Literal["wording", "evidence_interpretation", "scope_boundary", "contradictory"]


class DiscrepancyResponse(BaseModel):
    project_id: UUID
    friction_points: list[FrictionPoint]
    semantic_overlap: float
    recommendation: str
    run_id: UUID
