from pathlib import Path

import pytest

from appealpilot.ingest import chunk_policy
from appealpilot.retrieval import HybridSearcher, InMemoryStore

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def policy_text() -> str:
    return (SAMPLES / "policy_wording.txt").read_text()


@pytest.fixture
def denial_text() -> str:
    return (SAMPLES / "denial_letter.txt").read_text()


@pytest.fixture
def searcher(policy_text) -> HybridSearcher:
    s = HybridSearcher(InMemoryStore())
    s.index("c1", chunk_policy("policy", policy_text))
    return s
