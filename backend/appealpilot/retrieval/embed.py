"""Embeddings behind a tiny interface so the vector side is swappable.

`HashingEmbedder` is the default: deterministic, zero-download, zero-cost, and good
enough to complement BM25 (word + character-trigram feature hashing catches spelling
variants like "hospitalisation" / "hospitalization" and partial words).

For production, implement `Embedder` with a hosted model (e.g. Voyage AI) and set
`embed_dim` to match. The pgvector schema and the hybrid fusion do not change.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from .text import tokenize


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % self.dim
        sign = 1.0 if h[4] & 1 else -1.0
        return idx, sign

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for tok in tokenize(text):
                i, s = self._bucket("w:" + tok)
                out[row, i] += s
                padded = f"#{tok}#"
                for j in range(len(padded) - 2):
                    i, s = self._bucket("c:" + padded[j : j + 3])
                    out[row, i] += 0.3 * s
            norm = np.linalg.norm(out[row])
            if norm > 0:
                out[row] /= norm
        return out
