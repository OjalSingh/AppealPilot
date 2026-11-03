"""A small, dependency-free Okapi BM25 index."""

from __future__ import annotations

import math
from collections import Counter

from .text import tokenize


class BM25:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[Counter[str]] = []
        self.lengths: list[int] = []
        self.df: Counter[str] = Counter()

    def add(self, text: str) -> None:
        tf = Counter(tokenize(text))
        self.docs.append(tf)
        self.lengths.append(sum(tf.values()))
        self.df.update(tf.keys())

    def scores(self, query: str) -> list[float]:
        n = len(self.docs)
        if n == 0:
            return []
        avgdl = sum(self.lengths) / n
        q = tokenize(query)
        out = [0.0] * n
        for term in set(q):
            df = self.df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, tf in enumerate(self.docs):
                f = tf.get(term, 0)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / avgdl)
                    out[i] += idf * f * (self.k1 + 1) / denom
        return out
