"""Deterministic, no-LLM versions of the agent's reasoning steps.

Used when no ANTHROPIC_API_KEY is set (local demo, CI, the retrieval eval), and as a
baseline the Claude agent has to beat in the eval.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .schemas import AppealDraft, Citation, Denial, DenialCategory, SearchHit

_CATEGORY_KEYWORDS: list[tuple[DenialCategory, tuple[str, ...]]] = [
    (DenialCategory.PRE_EXISTING, ("pre-existing", "pre existing", "ped", "excl01")),
    (
        DenialCategory.NON_DISCLOSURE,
        ("non-disclosure", "non disclosure", "misrepresent", "suppress"),
    ),
    (
        DenialCategory.MISSING_DOCUMENTS,
        ("documents not submitted", "pending documents", "non-submission"),
    ),
    (DenialCategory.WAITING_PERIOD, ("waiting period", "excl02", "excl03", "first 30 days")),
    (DenialCategory.ROOM_RENT_LIMIT, ("room rent", "proportionate", "room category", "sub-limit")),
    (
        DenialCategory.NOT_MEDICALLY_NECESSARY,
        ("medically necessary", "medical necessity", "not required", "could have been treated"),
    ),
    (
        DenialCategory.DAYCARE_OPD,
        ("opd", "outpatient", "less than 24 hours", "daycare", "day care"),
    ),
    (
        DenialCategory.LATE_INTIMATION,
        ("late intimation", "intimated late", "delay in intimation", "beyond"),
    ),
    (DenialCategory.EXCLUSION, ("excluded", "exclusion", "not payable", "not covered")),
]

# What to search the policy for, per denial type. The goal is the clause that limits
# or contradicts the denial, not only the one the insurer quoted.
CATEGORY_QUERIES: dict[DenialCategory, list[str]] = {
    DenialCategory.PRE_EXISTING: [
        "pre-existing disease definition diagnosed within 48 months prior",
        "moratorium period eight years continuous coverage no claim contestable",
    ],
    DenialCategory.NON_DISCLOSURE: [
        "moratorium period eight years continuous coverage contestable fraud",
        "non disclosure misrepresentation material fact",
    ],
    DenialCategory.WAITING_PERIOD: [
        "specified disease waiting period months",
        "portability continuity waiting period credit previous policy",
        "30 days initial waiting period accident exception",
    ],
    DenialCategory.ROOM_RENT_LIMIT: [
        "room rent limit proportionate deduction",
        "proportionate deduction not applicable medicines consumables ICU",
    ],
    DenialCategory.NOT_MEDICALLY_NECESSARY: [
        "medically necessary treatment definition",
        "hospitalisation definition in-patient care 24 hours",
    ],
    DenialCategory.DAYCARE_OPD: [
        "day care treatment less than 24 hours technology",
        "hospitalisation definition in-patient care 24 hours",
    ],
    DenialCategory.LATE_INTIMATION: [
        "claim intimation notification time limit",
        "condonation of delay claims genuine reasons",
    ],
    DenialCategory.MISSING_DOCUMENTS: ["claim documents required submission time limit"],
    DenialCategory.EXCLUSION: [
        "exclusions not payable",
        "rejection communicated in writing stating the specific clause relied upon",
    ],
    DenialCategory.OTHER: [
        "rejection communicated in writing stating the specific clause relied upon",
        "coverage scope benefits",
    ],
}

_AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)", re.I)
_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b|\b(\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4})\b")
_CLAIM_NO = re.compile(r"(?i)claim\s*(?:no\.?|number|id)\s*[:#]?\s*([A-Z0-9/-]{5,})")
_CLAUSE_REF = re.compile(
    r"(?i)(?:clause|section|exclusion|condition)\s*(?:no\.?\s*)?(\d{1,2}(?:\.\d{1,2}){0,3})|\b(excl\s?\d{2})\b"
)
_REASON = re.compile(
    r"(?is)(?:reason(?: for (?:rejection|repudiation|denial))?|grounds?)\s*[:\-]\s*(.+?)(?:\n\s*\n|$)"
)


def _parse_date(text: str) -> date | None:
    m = _DATE.search(text)
    if not m:
        return None
    if m.group(1):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%d %B, %Y", "%d %b, %Y"):
        try:
            return datetime.strptime(m.group(4), fmt).date()
        except ValueError:
            continue
    return None


def classify(text: str) -> DenialCategory:
    low = text.lower()
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k in low for k in kws):
            return cat
    return DenialCategory.OTHER


def _classify_reason(reason: str, text: str) -> DenialCategory:
    """The stated reason is the strongest signal; the rest of the letter is a fallback."""
    cat = classify(reason)
    return cat if cat is not DenialCategory.OTHER else classify(text)


def extract_denial(text: str) -> Denial:
    reason_m = _REASON.search(text)
    reason = (reason_m.group(1) if reason_m else text[:400]).strip()
    amounts = [float(a.replace(",", "")) for a in _AMOUNT.findall(text)]
    refs = []
    for num, excl in _CLAUSE_REF.findall(text):
        ref = num or excl.upper().replace(" ", "")
        if ref and ref not in refs:
            refs.append(ref)
    claim = _CLAIM_NO.search(text)
    insurer = re.search(
        r"(?im)^\s*([A-Z][\w&. ]+(?:Insurance|Assurance)[\w&. ]*(?:Ltd|Limited)?\.?)", text
    )
    return Denial(
        insurer=insurer.group(1).strip() if insurer else None,
        claim_number=claim.group(1) if claim else None,
        denial_date=_parse_date(text),
        amount_claimed=max(amounts) if amounts else None,
        category=_classify_reason(reason, text),
        reason_text=re.sub(r"\s+", " ", reason)[:600].rstrip(". "),
        clauses_cited_by_insurer=refs,
    )


def queries_for(denial: Denial) -> list[str]:
    qs = [denial.reason_text]
    qs += [f"clause {r}" for r in denial.clauses_cited_by_insurer]
    qs += CATEGORY_QUERIES.get(denial.category, CATEGORY_QUERIES[DenialCategory.OTHER])
    return qs


_ARGUMENTS: dict[DenialCategory, str] = {
    DenialCategory.PRE_EXISTING: (
        "The condition does not meet the policy's own definition of a pre-existing disease, "
        "and/or the moratorium clause bars this ground after continuous coverage."
    ),
    DenialCategory.NON_DISCLOSURE: (
        "After the moratorium period the policy cannot be contested for non-disclosure except "
        "for established fraud, which the insurer has not alleged."
    ),
    DenialCategory.WAITING_PERIOD: (
        "The waiting period has been served when continuous prior coverage is credited, or "
        "the treatment falls outside the specific-disease waiting list."
    ),
    DenialCategory.ROOM_RENT_LIMIT: (
        "Proportionate deduction cannot be applied to items the policy excludes from it, such "
        "as medicines, consumables and ICU charges."
    ),
    DenialCategory.NOT_MEDICALLY_NECESSARY: (
        "The treating doctor prescribed the treatment, which meets the policy's definition of "
        "medically necessary treatment."
    ),
    DenialCategory.DAYCARE_OPD: (
        "The procedure is covered as day-care treatment, which the policy explicitly exempts "
        "from the 24-hour hospitalisation requirement."
    ),
    DenialCategory.LATE_INTIMATION: (
        "The policy allows delayed intimation for genuine reasons, and the delay did not "
        "prejudice the insurer's assessment."
    ),
}


def _quote(text: str, limit: int = 260) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "..."


def draft_letter(denial: Denial, hits: list[SearchHit], missing_docs: list[str]) -> AppealDraft:
    argument = _ARGUMENTS.get(
        denial.category, "The stated ground is not supported by the policy wording."
    )
    citations = [
        Citation(clause_id=h.clause.id, quote=_quote(h.clause.text), argument=argument)
        for h in hits[:3]
    ]
    cited_lines = "\n".join(
        f'- Clause {c.clause_id.split(":", 1)[-1]}: "{c.quote}"' for c in citations
    )
    claim = denial.claim_number or "[claim number]"
    body = f"""To the Grievance Redressal Officer,
{denial.insurer or "[Insurer name]"}

Subject: Appeal against rejection of claim {claim}

I am writing to appeal the decision{f" dated {denial.denial_date:%d %B %Y}" if denial.denial_date else ""} to reject my claim{f" of Rs {denial.amount_claimed:,.0f}" if denial.amount_claimed else ""}. The letter gives the reason as: "{denial.reason_text}".

I request a review because the policy wording does not support this decision:

{cited_lines or "- [Cite the relevant clauses]"}

{argument}

I request that the claim be re-examined and settled in full{"" if not missing_docs else ", and I am attaching the following supporting documents: " + "; ".join(missing_docs)}. If the decision is upheld, please give the specific clause relied on and the evidence for it, so I can take the matter to the Insurance Ombudsman.

Yours sincerely,
[Name]
[Policy number] | [Contact]"""
    return AppealDraft(
        subject=f"Appeal against rejection of claim {claim}",
        body=body,
        citations=citations,
        requested_relief="Re-examine and settle the claim in full",
    )
