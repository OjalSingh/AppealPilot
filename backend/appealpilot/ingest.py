"""Turn uploaded files into text, and policy wordings into clause-level chunks.

Clause-level chunking matters: an appeal has to cite "Section 4.2.1", not "chunk 17".
We split on the numbering that Indian health-policy wordings use (1., 4.2, 4.2.1, (a)),
and keep each clause's number and title so citations are exact.
"""

from __future__ import annotations

import io
import re

from pypdf import PdfReader

from .schemas import Clause

# "4.2.1 Pre-existing Diseases (Code- Excl01)" / "Section 3 - Definitions" / "Clause 7:"
_HEADING = re.compile(
    r"^\s*(?:(?:section|clause|article)\s+)?"
    r"(?P<num>\d{1,2}(?:\.\d{1,2}){1,3}|\d{1,2}(?=[.)]))[.)]?\s+(?P<title>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_text(filename: str, data: bytes) -> str:
    """Extract text from a PDF or plain-text upload.

    Scanned PDFs with no text layer return an empty string; in Claude mode those
    are sent to the model as PDF documents so vision can read them.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff":
        return ""  # image: Claude reads it with vision; the offline planner cannot OCR
    if filename.lower().endswith(".pdf") or data[:4] == b"%PDF":
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    return data.decode("utf-8", errors="replace").strip()


def _short_title(line: str) -> str | None:
    """'Pre-Existing Diseases (Code- Excl01). Expenses ...' -> 'Pre-Existing Diseases (Code- Excl01)'"""
    head = re.split(r"(?<=[a-z0-9)])\.\s|\s(?:means|shall|is)\s", line.strip(), maxsplit=1)[0]
    head = head.strip(" -:.")
    return head[:90] or None


def chunk_policy(doc_id: str, text: str, max_chars: int = 1800) -> list[Clause]:
    """Split a policy wording into clauses keyed by their section number."""
    matches = list(_HEADING.finditer(text))
    clauses: list[Clause] = []

    if not matches:
        # No numbering found: fall back to paragraph windows so search still works.
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for i, para in enumerate(paras):
            clauses.append(Clause(id=f"{doc_id}:p{i + 1}", doc_id=doc_id, text=para[:max_chars]))
        return clauses

    preamble = text[: matches[0].start()].strip()
    if preamble:
        clauses.append(
            Clause(id=f"{doc_id}:preamble", doc_id=doc_id, title="Preamble", text=preamble)
        )

    seen: dict[str, int] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start() : end].strip()
        num = m.group("num")
        # Duplicate numbers happen (schedule tables restart numbering); keep ids unique.
        seen[num] = seen.get(num, 0) + 1
        cid = f"{doc_id}:{num}" if seen[num] == 1 else f"{doc_id}:{num}#{seen[num]}"
        if len(body) < 40:  # bare section header like "2. Definitions"
            continue
        title = _short_title(m.group("title"))
        clauses.append(
            Clause(id=cid, doc_id=doc_id, number=num, title=title, text=body[:max_chars])
        )
    return clauses
