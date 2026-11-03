"""Escalation timeline for Indian health-insurance disputes.

The ladder: insurer's grievance cell -> Insurance Ombudsman (Insurance Ombudsman Rules,
2017) -> consumer commission. The day counts are kept in one table so they are easy to
review and update when IRDAI changes them. This is information, not legal advice.
"""

from __future__ import annotations

from datetime import date, timedelta

from .schemas import Deadline

RULES = {
    "grievance_recommended_days": 15,
    "insurer_response_days": 14,
    "ombudsman_wait_days": 30,
    "ombudsman_limit_days": 365,
    "ombudsman_claim_cap_inr": 5_000_000,
}

_OMBUDSMAN_SRC = "Insurance Ombudsman Rules, 2017 (Rule 14); cioins.co.in"
_IRDAI_SRC = "IRDAI (Protection of Policyholders' Interests) Regulations and master circular, 2024"


def build_deadlines(
    denial_date: date | None,
    grievance_filed: date | None = None,
    today: date | None = None,
    amount_claimed: float | None = None,
) -> list[Deadline]:
    today = today or date.today()
    base = denial_date or today
    filed = grievance_filed or max(today, base)
    out = [
        Deadline(
            step="file_grievance",
            due=base + timedelta(days=RULES["grievance_recommended_days"]),
            description=(
                "Send the appeal to the insurer's grievance officer (email + IGMS / Bima "
                "Bharosa). Not a legal deadline, but filing early keeps every later window open."
            ),
            source="AppealPilot recommendation",
        ),
        Deadline(
            step="insurer_reply_due",
            due=filed + timedelta(days=RULES["insurer_response_days"]),
            description="The insurer should resolve the grievance within this window.",
            source=_IRDAI_SRC,
        ),
        Deadline(
            step="ombudsman_eligible",
            due=filed + timedelta(days=RULES["ombudsman_wait_days"]),
            description=(
                "If the insurer rejects the grievance or has not replied, you can complain to "
                "the Insurance Ombudsman from this date (earlier if they reject it sooner)."
            ),
            source=_OMBUDSMAN_SRC,
        ),
        Deadline(
            step="ombudsman_last_date",
            due=base + timedelta(days=RULES["ombudsman_limit_days"]),
            description=(
                "Last day to complain to the Ombudsman: one year from the insurer's final reply. "
                "Recalculate from the grievance reply date once you have it."
            ),
            source=_OMBUDSMAN_SRC,
        ),
    ]
    if amount_claimed and amount_claimed > RULES["ombudsman_claim_cap_inr"]:
        out.append(
            Deadline(
                step="consumer_commission",
                due=base + timedelta(days=730),
                description=(
                    "Claim is above the Ombudsman's Rs 50 lakh cap; the route is the consumer "
                    "commission (two years from the cause of action)."
                ),
                source="Consumer Protection Act, 2019 (Section 69)",
            )
        )
    return sorted(out, key=lambda d: d.due)
