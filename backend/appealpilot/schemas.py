"""Typed data model shared by the agent tools, the API and the eval harness."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class DenialCategory(StrEnum):
    WAITING_PERIOD = "waiting_period"
    PRE_EXISTING = "pre_existing_disease"
    NOT_MEDICALLY_NECESSARY = "not_medically_necessary"
    EXCLUSION = "policy_exclusion"
    ROOM_RENT_LIMIT = "room_rent_limit"
    MISSING_DOCUMENTS = "missing_documents"
    NON_DISCLOSURE = "non_disclosure"
    DAYCARE_OPD = "daycare_or_opd"
    LATE_INTIMATION = "late_intimation"
    OTHER = "other"


class Denial(BaseModel):
    """What the insurer said, pulled out of the denial / repudiation letter."""

    insurer: str | None = None
    claim_number: str | None = None
    denial_date: date | None = None
    amount_claimed: float | None = None
    amount_paid: float | None = None
    category: DenialCategory = DenialCategory.OTHER
    reason_text: str = Field(
        description="The insurer's stated reason, quoted as closely as possible"
    )
    clauses_cited_by_insurer: list[str] = Field(default_factory=list)
    diagnosis: str | None = None


class Clause(BaseModel):
    id: str = Field(description="Stable id, e.g. 'policy:4.2.1'")
    doc_id: str
    number: str | None = None
    title: str | None = None
    text: str


class SearchHit(BaseModel):
    clause: Clause
    score: float
    bm25_rank: int | None = None
    vector_rank: int | None = None


class DocumentCheck(BaseModel):
    present: list[str]
    missing: list[str]
    notes: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    clause_id: str
    quote: str
    argument: str = Field(description="Why this clause contradicts or limits the denial")


class AppealDraft(BaseModel):
    subject: str
    body: str
    citations: list[Citation]
    requested_relief: str


class Deadline(BaseModel):
    step: str
    due: date
    description: str
    source: str


class CaseResult(BaseModel):
    case_id: str
    denial: Denial
    hits: list[SearchHit] = Field(default_factory=list)
    documents: DocumentCheck | None = None
    appeal: AppealDraft | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list, description="Redacted tool-call trace")
    mode: str = Field(description="'claude' or 'offline'")
    usage: dict = Field(default_factory=dict)
