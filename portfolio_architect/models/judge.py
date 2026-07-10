from typing import Literal
from uuid import UUID
from pydantic import BaseModel


class JudgeScoreDimension(BaseModel):
    score: int
    rationale: str


class JudgeVerdict(BaseModel):
    run_id: UUID
    stage: Literal["structural", "logical"]
    faithfulness: JudgeScoreDimension | None = None
    problem_statement_integrity: JudgeScoreDimension | None = None
    citation_accuracy: JudgeScoreDimension | None = None
    uncertainty_transparency: JudgeScoreDimension | None = None
    overall: int | None = None
    verdict: Literal["pass", "fail", "death_spiral"]
    death_spiral_reason: str | None = None


class JudgeResult(BaseModel):
    structural: JudgeVerdict
    logical: JudgeVerdict | None = None
    final_verdict: Literal["pass", "fail", "death_spiral"]
