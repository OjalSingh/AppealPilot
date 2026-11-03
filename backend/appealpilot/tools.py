"""The agent's five typed tools, and the state they build up for one case.

Every tool is read-only with respect to the outside world: the agent can search,
check and draft, but it cannot send anything. A human files the appeal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from .deadlines import build_deadlines
from .documents import UploadedDoc, check_documents
from .retrieval import HybridSearcher
from .schemas import (
    AppealDraft,
    Deadline,
    Denial,
    DenialCategory,
    DocumentCheck,
    SearchHit,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_is_grounded(quote: str, clause_text: str) -> bool:
    """True when every '...'-separated fragment of the quote appears verbatim in the clause."""
    hay = _norm(clause_text)
    parts = [p for p in (_norm(x).strip(" .\"'") for x in re.split(r"\.\.\.|…", quote)) if p]
    return bool(parts) and all(p in hay for p in parts)


@dataclass
class CaseState:
    case_id: str
    docs: list[UploadedDoc]
    today: date = field(default_factory=date.today)
    denial: Denial | None = None
    hits: dict[str, SearchHit] = field(default_factory=dict)
    documents: DocumentCheck | None = None
    appeal: AppealDraft | None = None
    deadlines: list[Deadline] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)


TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "extract_denial",
        "description": (
            "Record the structured facts of the denial letter you have read: insurer, claim "
            "number, dates, amounts, the stated reason (quoted), the denial category, and any "
            "clause numbers the insurer cited. Call this first, once."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "insurer": {"type": ["string", "null"]},
                "claim_number": {"type": ["string", "null"]},
                "denial_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "amount_claimed": {"type": ["number", "null"]},
                "amount_paid": {"type": ["number", "null"]},
                "category": {"type": "string", "enum": [c.value for c in DenialCategory]},
                "reason_text": {"type": "string"},
                "clauses_cited_by_insurer": {"type": "array", "items": {"type": "string"}},
                "diagnosis": {"type": ["string", "null"]},
            },
            "required": [
                "insurer",
                "claim_number",
                "denial_date",
                "amount_claimed",
                "amount_paid",
                "category",
                "reason_text",
                "clauses_cited_by_insurer",
                "diagnosis",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "search_policy",
        "description": (
            "Hybrid (keyword + semantic) search over this customer's policy wording. Returns "
            "clause ids, numbers and full text. Search for the clause the insurer relied on AND "
            "for clauses that limit or contradict it (definitions, moratorium, exceptions, "
            "portability credit). Use several focused queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "description": "Results to return, 1-8"},
            },
            "required": ["query", "k"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "check_documents",
        "description": (
            "List which supporting documents for this denial category are already uploaded "
            "and which are missing. Call after extract_denial."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": [c.value for c in DenialCategory]}
            },
            "required": ["category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "draft_letter",
        "description": (
            "Submit the appeal letter. Every citation must use a clause_id returned by "
            "search_policy and a quote copied verbatim from that clause's text (use '...' to "
            "skip words). Ungrounded citations are rejected and you must fix them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Full letter text, plain prose"},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "clause_id": {"type": "string"},
                            "quote": {"type": "string"},
                            "argument": {"type": "string"},
                        },
                        "required": ["clause_id", "quote", "argument"],
                        "additionalProperties": False,
                    },
                },
                "requested_relief": {"type": "string"},
            },
            "required": ["subject", "body", "citations", "requested_relief"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "schedule_deadline",
        "description": (
            "Compute the escalation timeline (insurer grievance, Ombudsman window and last "
            "date) from the denial date. Call once after draft_letter is accepted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "denial_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "grievance_filed": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            },
            "required": ["denial_date", "grievance_filed"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class Toolbox:
    def __init__(self, state: CaseState, searcher: HybridSearcher):
        self.state = state
        self.searcher = searcher

    # -- individual tools -------------------------------------------------
    def extract_denial(self, **kw) -> dict:
        self.state.denial = Denial(**kw)
        return {"ok": True, "denial": self.state.denial.model_dump(mode="json")}

    def search_policy(self, query: str, k: int = 5) -> dict:
        hits = self.searcher.search(self.state.case_id, query, k=max(1, min(int(k), 8)))
        for h in hits:
            self.state.hits.setdefault(h.clause.id, h)
        return {
            "results": [
                {
                    "clause_id": h.clause.id,
                    "number": h.clause.number,
                    "title": h.clause.title,
                    "text": h.clause.text,
                    "score": h.score,
                }
                for h in hits
            ]
        }

    def check_documents(self, category: str) -> dict:
        self.state.documents = check_documents(DenialCategory(category), self.state.docs)
        return self.state.documents.model_dump()

    def draft_letter(self, **kw) -> dict:
        draft = AppealDraft(**kw)
        problems = []
        for c in draft.citations:
            clause = self.searcher.store.get_clause(self.state.case_id, c.clause_id)
            if clause is None:
                problems.append(f"{c.clause_id}: unknown clause id; use one from search_policy")
            elif not quote_is_grounded(c.quote, clause.text):
                problems.append(f"{c.clause_id}: quote not found verbatim in the clause text")
        if not draft.citations:
            problems.append("an appeal needs at least one policy citation")
        if problems:
            return {"ok": False, "errors": problems}
        self.state.appeal = draft
        return {"ok": True}

    def schedule_deadline(self, denial_date: str | None, grievance_filed: str | None) -> dict:
        dd = (
            date.fromisoformat(denial_date)
            if denial_date
            else (self.state.denial.denial_date if self.state.denial else None)
        )
        gf = date.fromisoformat(grievance_filed) if grievance_filed else None
        amount = self.state.denial.amount_claimed if self.state.denial else None
        self.state.deadlines = build_deadlines(
            dd, gf, today=self.state.today, amount_claimed=amount
        )
        return {"deadlines": [d.model_dump(mode="json") for d in self.state.deadlines]}

    # -- dispatch ---------------------------------------------------------
    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a tool call. Returns (json_result, is_error)."""
        fn = getattr(self, name, None)
        if name not in {t["name"] for t in TOOL_DEFS} or fn is None:
            return json.dumps({"error": f"unknown tool {name}"}), True
        try:
            result = fn(**args)
            is_error = result.get("ok") is False
        except (ValidationError, ValueError, TypeError) as e:
            result, is_error = {"error": str(e)[:800]}, True
        return json.dumps(result, default=str), is_error
