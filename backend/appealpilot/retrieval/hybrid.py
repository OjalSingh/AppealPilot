"""Hybrid retrieval: BM25 + vector search fused with Reciprocal Rank Fusion, then reranked.

Why hybrid: denial letters quote exact clause wording ("Code-Excl03", "30 days"), which
lexical search nails, while users and models paraphrase ("my knee surgery waiting time"),
which vectors handle. RRF needs no score calibration between the two.
"""

from __future__ import annotations

import re

from ..schemas import Clause, SearchHit
from .embed import Embedder, HashingEmbedder
from .store import PolicyStore

_NUM_REF = re.compile(r"\b(\d{1,2}(?:\.\d{1,2}){1,3})\b")


class HybridSearcher:
    def __init__(self, store: PolicyStore, embedder: Embedder | None = None, rrf_k: int = 60):
        self.store = store
        self.embedder = embedder or HashingEmbedder()
        self.rrf_k = rrf_k

    def index(self, case_id: str, clauses: list[Clause]) -> int:
        if not clauses:
            return 0
        vectors = self.embedder.embed([f"{c.title or ''} {c.text}" for c in clauses])
        self.store.add_clauses(case_id, clauses, vectors)
        return len(clauses)

    def search(self, case_id: str, query: str, k: int = 5, pool: int = 25) -> list[SearchHit]:
        lexical = self.store.lexical_rank(case_id, query, pool)
        qvec = self.embedder.embed([query])[0]
        vector = self.store.vector_rank(case_id, qvec, pool)

        fused: dict[str, dict] = {}
        for rank, (clause, _) in enumerate(lexical, start=1):
            e = fused.setdefault(clause.id, {"clause": clause, "score": 0.0})
            e["score"] += 1.0 / (self.rrf_k + rank)
            e["bm25_rank"] = rank
        for rank, (clause, _) in enumerate(vector, start=1):
            e = fused.setdefault(clause.id, {"clause": clause, "score": 0.0})
            e["score"] += 1.0 / (self.rrf_k + rank)
            e["vector_rank"] = rank

        # Rerank: a clause whose number is quoted in the query (the insurer cited it) is
        # almost always relevant, so it goes to the top.
        cited = set(_NUM_REF.findall(query))
        for e in fused.values():
            if e["clause"].number and e["clause"].number in cited:
                e["score"] += 1.0
            # Definitions and preambles match everything lexically; nudge them down.
            title = (e["clause"].title or "").lower()
            if "definition" in title or e["clause"].id.endswith(":preamble"):
                e["score"] *= 0.8

        ranked = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:k]
        return [
            SearchHit(
                clause=e["clause"],
                score=round(e["score"], 5),
                bm25_rank=e.get("bm25_rank"),
                vector_rank=e.get("vector_rank"),
            )
            for e in ranked
        ]
