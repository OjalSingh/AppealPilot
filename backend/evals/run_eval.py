"""Evaluate AppealPilot on labelled denial cases.

Metrics
- category_accuracy: denial type classified correctly
- recall_at_5: at least one gold clause is in the top-5 retrieved clauses
- citation_hit_rate: the final appeal cites at least one gold clause
- grounded_rate: every citation's quote appears verbatim in the cited clause
- (claude mode) tokens, turns, latency and cost per case

Usage:
    python evals/run_eval.py                    # offline baseline, free, runs in CI
    python evals/run_eval.py --mode claude      # needs ANTHROPIC_API_KEY
    python evals/run_eval.py --split heldout    # second policy, never tuned against
    python evals/run_eval.py --min-recall 0.8   # exit 1 if below (CI gate)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from appealpilot.agent import AppealAgent  # noqa: E402
from appealpilot.config import Settings  # noqa: E402
from appealpilot.documents import UploadedDoc  # noqa: E402
from appealpilot.ingest import chunk_policy  # noqa: E402
from appealpilot.retrieval import HybridSearcher, InMemoryStore  # noqa: E402
from appealpilot.tools import CaseState, quote_is_grounded  # noqa: E402

SAMPLES = ROOT.parents[1] / "samples"
# USD per million tokens (input, output) for cost reporting.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.1, 0.5),
}


def run(mode: str, model: str, limit: int | None, split: str = "dev") -> dict:
    name = "cases.jsonl" if split == "dev" else "cases_heldout.jsonl"
    cases = [json.loads(line) for line in (ROOT / name).read_text().splitlines() if line]
    cases = cases[:limit] if limit else cases
    settings = Settings(appealpilot_model=model)
    if mode == "offline":
        settings.anthropic_api_key = None
    elif not settings.anthropic_api_key:
        sys.exit("--mode claude needs ANTHROPIC_API_KEY")

    rows = []
    for case in cases:
        store = InMemoryStore()
        searcher = HybridSearcher(store)
        policy_text = (SAMPLES / case["policy"]).read_text()
        searcher.index(case["id"], chunk_policy("policy", policy_text))
        docs = [
            UploadedDoc(case["policy"], "policy", policy_text),
            UploadedDoc("denial.txt", "denial", case["denial_text"]),
        ]
        state = CaseState(case_id=case["id"], docs=docs, today=date(2026, 11, 3))
        result = AppealAgent(searcher, settings).run(state)

        gold = set(case["gold_clauses"])
        top5 = [h.clause.id for h in result.hits[:5]]
        cited = [c.clause_id for c in result.appeal.citations] if result.appeal else []
        grounded = all(
            (cl := store.get_clause(case["id"], c.clause_id)) is not None
            and quote_is_grounded(c.quote, cl.text)
            for c in (result.appeal.citations if result.appeal else [])
        )
        u = result.usage or {}
        pin, pout = PRICES.get(model, (0, 0))
        cost = (u.get("input_tokens", 0) * pin + u.get("output_tokens", 0) * pout) / 1e6
        rows.append(
            {
                "id": case["id"],
                "mode": result.mode,
                "category_ok": result.denial.category.value == case["expected_category"],
                "predicted_category": result.denial.category.value,
                "recall_at_5": bool(gold & set(top5)),
                "citation_hit": bool(gold & set(cited)),
                "grounded": grounded,
                "cited": cited,
                "gold": sorted(gold),
                "turns": u.get("turns", 0),
                "latency_s": u.get("latency_s", 0),
                "cost_usd": round(cost, 4),
            }
        )

    n = len(rows)
    summary = {
        "mode": mode,
        "split": split,
        "model": model if mode == "claude" else None,
        "cases": n,
        "category_accuracy": round(sum(r["category_ok"] for r in rows) / n, 3),
        "recall_at_5": round(sum(r["recall_at_5"] for r in rows) / n, 3),
        "citation_hit_rate": round(sum(r["citation_hit"] for r in rows) / n, 3),
        "grounded_rate": round(sum(r["grounded"] for r in rows) / n, 3),
        "avg_cost_usd": round(sum(r["cost_usd"] for r in rows) / n, 4),
        "avg_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "claude"], default="offline")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--split", choices=["dev", "heldout"], default="dev")
    ap.add_argument("--min-recall", type=float, default=0.0)
    ap.add_argument("--min-citation", type=float, default=0.0)
    args = ap.parse_args()

    report = run(args.mode, args.model, args.limit, args.split)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / f"{args.mode}-{args.split}.json").write_text(json.dumps(report, indent=2))

    s = report["summary"]
    print(json.dumps(s, indent=2))
    for r in report["rows"]:
        if not (r["category_ok"] and r["recall_at_5"] and r["citation_hit"] and r["grounded"]):
            print(
                f"  miss {r['id']}: cat={r['predicted_category']} cited={r['cited']} gold={r['gold']}"
            )

    if s["recall_at_5"] < args.min_recall or s["citation_hit_rate"] < args.min_citation:
        sys.exit(
            f"eval below threshold: recall {s['recall_at_5']}, citation {s['citation_hit_rate']}"
        )


if __name__ == "__main__":
    main()
