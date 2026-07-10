from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class DocumentCreate(BaseModel):
    content: str
    source_id: str
    doc_type: Literal["paper", "scope_definition", "trial", "other"] = "paper"


class DocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_id: str
    doc_type: str
    chunk_count: int
    embedded: bool
    created_at: datetime


class ChunkResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    source_id: str
    content: str
    score: float
