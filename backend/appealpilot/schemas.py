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


class CaseKind(StrEnum):
    INSURANCE = "insurance"
    CHALLAN = "challan"


class Ground(StrEnum):
    NOTICE_TIME_BARRED = "notice_time_barred"
    WRONG_VEHICLE = "wrong_vehicle"
    PLATE_CLONED = "plate_cloned"
    VEHICLE_SOLD = "vehicle_sold"
    ALREADY_PAID = "already_paid"
    WRONG_OFFENCE = "wrong_offence"
    NO_NOTICE_RECEIVED = "no_notice_received"
    NOTICE_INCOMPLETE = "notice_incomplete"
    SIGNAGE_ABSENT = "signage_absent"


class Challan(BaseModel):
    """A traffic challan / e-challan notice."""

    challan_number: str | None = None
    vehicle_number: str | None = None
    offence: str | None = None
    section: str | None = None
    offence_date: date | None = None
    notice_date: date | None = None
    amount: float | None = None
    location: str | None = None
    authority: str | None = None
    is_echallan: bool = True


class GroundFinding(BaseModel):
    ground: Ground
    strength: str = Field(
        description="'strong' (the documents alone show it) or 'possible' (needs your evidence)"
    )
    why: str
    evidence_needed: list[str] = Field(default_factory=list)
    guide_ids: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    case_id: str
    kind: CaseKind = CaseKind.INSURANCE
    denial: Denial | None = None
    challan: Challan | None = None
    findings: list[GroundFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    hits: list[SearchHit] = Field(default_factory=list)
    documents: DocumentCheck | None = None
    appeal: AppealDraft | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list, description="Redacted tool-call trace")
    mode: str = Field(description="'claude' or 'offline'")
    usage: dict = Field(default_factory=dict)
