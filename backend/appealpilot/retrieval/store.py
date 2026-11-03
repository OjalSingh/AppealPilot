"""Clause + case storage. In-memory for dev/tests, Postgres + pgvector for real deployments.

Everything is scoped by `case_id`: a user's policy wording is only ever searched for
that user's case, and `delete_case` removes every trace of it (the delete-my-data button).
"""

from __future__ import annotations

import json
from typing import Protocol

import numpy as np

from ..schemas import Clause
from .bm25 import BM25
from .text import tokenize


class PolicyStore(Protocol):
    def add_clauses(self, case_id: str, clauses: list[Clause], vectors: np.ndarray) -> None: ...
    def lexical_rank(self, case_id: str, query: str, k: int) -> list[tuple[Clause, float]]: ...
    def vector_rank(self, case_id: str, qvec: np.ndarray, k: int) -> list[tuple[Clause, float]]: ...
    def get_clause(self, case_id: str, clause_id: str) -> Clause | None: ...
    def save_case(self, case_id: str, data: dict) -> None: ...
    def get_case(self, case_id: str) -> dict | None: ...
    def delete_case(self, case_id: str) -> bool: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._clauses: dict[str, list[Clause]] = {}
        self._vectors: dict[str, np.ndarray] = {}
        self._bm25: dict[str, BM25] = {}
        self._cases: dict[str, dict] = {}

    def add_clauses(self, case_id: str, clauses: list[Clause], vectors: np.ndarray) -> None:
        existing = self._clauses.setdefault(case_id, [])
        existing.extend(clauses)
        prev = self._vectors.get(case_id)
        self._vectors[case_id] = vectors if prev is None else np.vstack([prev, vectors])
        index = BM25()
        for c in existing:
            index.add(f"{c.title or ''} {c.text}")
        self._bm25[case_id] = index

    def lexical_rank(self, case_id: str, query: str, k: int) -> list[tuple[Clause, float]]:
        clauses = self._clauses.get(case_id, [])
        if not clauses:
            return []
        scores = self._bm25[case_id].scores(query)
        order = sorted(range(len(clauses)), key=lambda i: scores[i], reverse=True)
        return [(clauses[i], scores[i]) for i in order[:k] if scores[i] > 0]

    def vector_rank(self, case_id: str, qvec: np.ndarray, k: int) -> list[tuple[Clause, float]]:
        clauses = self._clauses.get(case_id, [])
        if not clauses:
            return []
        sims = self._vectors[case_id] @ qvec
        order = np.argsort(-sims)[:k]
        return [(clauses[int(i)], float(sims[int(i)])) for i in order]

    def get_clause(self, case_id: str, clause_id: str) -> Clause | None:
        return next((c for c in self._clauses.get(case_id, []) if c.id == clause_id), None)

    def save_case(self, case_id: str, data: dict) -> None:
        self._cases[case_id] = data

    def get_case(self, case_id: str) -> dict | None:
        return self._cases.get(case_id)

    def delete_case(self, case_id: str) -> bool:
        found = case_id in self._cases or case_id in self._clauses
        for d in (self._clauses, self._vectors, self._bm25, self._cases):
            d.pop(case_id, None)
        return found


class PgVectorStore:
    """Postgres store: full-text search for the lexical side, pgvector HNSW for the vector side."""

    def __init__(self, dsn: str, dim: int):
        import psycopg
        from pgvector.psycopg import register_vector

        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self._conn)
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS clauses (
                id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                number TEXT,
                title TEXT,
                text TEXT NOT NULL,
                tsv TSVECTOR GENERATED ALWAYS AS
                    (to_tsvector('english', coalesce(title, '') || ' ' || text)) STORED,
                embedding VECTOR({dim}) NOT NULL,
                PRIMARY KEY (case_id, id)
            );
            CREATE INDEX IF NOT EXISTS clauses_tsv_idx ON clauses USING GIN (tsv);
            CREATE INDEX IF NOT EXISTS clauses_vec_idx ON clauses
                USING hnsw (embedding vector_cosine_ops);
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )

    @staticmethod
    def _row(r) -> Clause:
        return Clause(id=r[0], doc_id=r[1], number=r[2], title=r[3], text=r[4])

    def add_clauses(self, case_id: str, clauses: list[Clause], vectors: np.ndarray) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO clauses (id, case_id, doc_id, number, title, text, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                [
                    (c.id, case_id, c.doc_id, c.number, c.title, c.text, v)
                    for c, v in zip(clauses, vectors, strict=True)
                ],
            )

    def lexical_rank(self, case_id: str, query: str, k: int) -> list[tuple[Clause, float]]:
        terms = sorted(set(tokenize(query)))
        if not terms:
            return []
        tsq = " | ".join(terms)
        rows = self._conn.execute(
            "SELECT id, doc_id, number, title, text, ts_rank_cd(tsv, q) AS s "
            "FROM clauses, to_tsquery('english', %s) q "
            "WHERE case_id = %s AND tsv @@ q ORDER BY s DESC LIMIT %s",
            (tsq, case_id, k),
        ).fetchall()
        return [(self._row(r), float(r[5])) for r in rows]

    def vector_rank(self, case_id: str, qvec: np.ndarray, k: int) -> list[tuple[Clause, float]]:
        rows = self._conn.execute(
            "SELECT id, doc_id, number, title, text, 1 - (embedding <=> %s) AS s "
            "FROM clauses WHERE case_id = %s ORDER BY embedding <=> %s LIMIT %s",
            (qvec, case_id, qvec, k),
        ).fetchall()
        return [(self._row(r), float(r[5])) for r in rows]

    def get_clause(self, case_id: str, clause_id: str) -> Clause | None:
        r = self._conn.execute(
            "SELECT id, doc_id, number, title, text FROM clauses WHERE case_id=%s AND id=%s",
            (case_id, clause_id),
        ).fetchone()
        return self._row(r) if r else None

    def save_case(self, case_id: str, data: dict) -> None:
        self._conn.execute(
            "INSERT INTO cases (case_id, data) VALUES (%s, %s) "
            "ON CONFLICT (case_id) DO UPDATE SET data = EXCLUDED.data",
            (case_id, json.dumps(data, default=str)),
        )

    def get_case(self, case_id: str) -> dict | None:
        r = self._conn.execute("SELECT data FROM cases WHERE case_id=%s", (case_id,)).fetchone()
        return r[0] if r else None

    def delete_case(self, case_id: str) -> bool:
        a = self._conn.execute("DELETE FROM clauses WHERE case_id=%s", (case_id,)).rowcount
        b = self._conn.execute("DELETE FROM cases WHERE case_id=%s", (case_id,)).rowcount
        return bool(a or b)


def make_store(database_url: str | None, dim: int) -> PolicyStore:
    if database_url:
        return PgVectorStore(database_url, dim)
    return InMemoryStore()
