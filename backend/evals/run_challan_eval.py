"""Evaluate the challan flow: does it find exactly the grounds the facts support?

Metrics
- exact_match: the set of grounds equals the labelled set
- strong_precision: every 'strong' ground is expected (a false 'strong' is the costly error,
  because a user may rely on it)
- grounded_rate: every citation in the letter is a `rule:` clause quoted verbatim

Usage: python evals/run_challan_eval.py [--mode claude]   (claude mode needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from appealpilot.challan import (  # noqa: E402
    ChallanAgent,
    ChallanFacts,
    ChallanState,
)
from appealpilot.config import Settings  # noqa: E402
from appealpilot.documents import UploadedDoc  # noqa: E402
from appealpilot.retrieval import HybridSearcher, InMemoryStore  # noqa: E402
from appealpilot.schemas import Ground  # noqa: E402
from appealpilot.tools import quote_is_grounded  # noqa: E402


def run(mode: str) -> dict:
    settings = Settings()
    if mode == "offline":
        settings.anthropic_api_key = None
    elif not settings.anthropic_api_key:
        sys.exit("--mode claude needs ANTHROPIC_API_KEY")
    rows = []
    for line in (ROOT / "challan_cases.jsonl").read_text().splitlines():
        case = json.loads(line)
        f = case["facts"]
        facts = ChallanFacts(
            sold_date=date.fromisoformat(f["sold_date"]) if f.get("sold_date") else None,
            is_echallan=f.get("is_echallan"),
            claims=[Ground(g) for g in f.get("grounds", [])],
            notes=f.get("notes", ""),
        )
        store = InMemoryStore()
        searcher = HybridSearcher(store)
        state = ChallanState(
            case["id"], [UploadedDoc("n.txt", "challan", case["text"])], facts, date(2026, 11, 4)
        )
        result = ChallanAgent(searcher, settings).run(state)
        got = {x.ground.value for x in result.findings}
        strong = {x.ground.value for x in result.findings if x.strength == "strong"}
        expected = set(case["expected"])
        grounded = all(
            c.clause_id.startswith("rule:")
            and (cl := store.get_clause(case["id"], c.clause_id)) is not None
            and quote_is_grounded(c.quote, cl.text)
            for c in result.appeal.citations
        )
        rows.append(
            {
                "id": case["id"],
                "mode": result.mode,
                "exact": got == expected,
                "strong_ok": strong <= expected,
                "grounded": grounded,
                "got": sorted(got),
                "expected": sorted(expected),
            }
        )
    n = len(rows)
    return {
        "summary": {
            "mode": mode,
            "cases": n,
            "claude_fallbacks": sum(mode == "claude" and r["mode"] != "claude" for r in rows),
            "exact_match": round(sum(r["exact"] for r in rows) / n, 3),
            "strong_precision": round(sum(r["strong_ok"] for r in rows) / n, 3),
            "grounded_rate": round(sum(r["grounded"] for r in rows) / n, 3),
        },
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "claude"], default="offline")
    ap.add_argument("--min-exact", type=float, default=0.0)
    args = ap.parse_args()
    report = run(args.mode)
    print(json.dumps(report["summary"], indent=2))
    for r in report["rows"]:
        if not (r["exact"] and r["strong_ok"] and r["grounded"]):
            print(f"  miss {r['id']}: got={r['got']} expected={r['expected']}")
    s = report["summary"]
    if s["claude_fallbacks"]:
        sys.exit(
            f"{s['claude_fallbacks']} of {s['cases']} cases fell back to the offline planner because "
            "the Claude call failed, so these numbers are NOT Claude's. Check the API key and logs."
        )
    if s["exact_match"] < args.min_exact or s["strong_precision"] < 1.0 or s["grounded_rate"] < 1.0:
        sys.exit("challan eval below threshold")


if __name__ == "__main__":
    main()
