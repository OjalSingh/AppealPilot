"""Tokenisation shared by BM25 and the hashing embedder, with insurance-domain synonyms."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")

_STOP = frozenset(
    (
        "a an and are as at be by for from has have in is it its of on or that the this to was "
        "were will with shall any such which under per all not no"
    ).split()
)

# Policy wordings and denial letters use different words for the same idea.
# Expanding both sides closes most of the lexical gap without a neural model.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ped": ("pre", "existing", "disease"),
    "preexisting": ("pre", "existing"),
    "hospitalisation": ("hospitalization",),
    "hospitalization": ("hospitalisation",),
    "repudiated": ("rejected", "denied"),
    "repudiation": ("rejection", "denial"),
    "rejected": ("denied", "repudiated"),
    "denied": ("rejected", "repudiated"),
    "daycare": ("day", "care"),
    "opd": ("outpatient",),
    "outpatient": ("opd",),
    "cataract": ("eye", "surgery"),
    "room": ("accommodation",),
    "icu": ("intensive", "care"),
    "intimation": ("notification", "notify", "inform"),
    "moratorium": ("eight", "years", "contestable"),
    "nondisclosure": ("non", "disclosure", "misrepresentation"),
    "proportionate": ("deduction", "ratio"),
}


def tokenize(text: str, expand: bool = True) -> list[str]:
    tokens = [t for t in _TOKEN.findall(text.lower().replace("-", "")) if t not in _STOP]
    if not expand:
        return tokens
    out: list[str] = []
    for t in tokens:
        out.append(t)
        out.extend(_SYNONYMS.get(t, ()))
    return out
