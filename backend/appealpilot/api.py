"""HTTP API. Run with: uvicorn appealpilot.api:app --reload"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response

from . import __version__
from .agent import AppealAgent
from .config import get_settings
from .documents import UploadedDoc
from .ingest import chunk_policy, extract_text
from .redact import install_log_redaction
from .retrieval import HybridSearcher, make_store
from .retrieval.embed import HashingEmbedder
from .schemas import CaseResult
from .tools import CaseState

install_log_redaction()
log = logging.getLogger("appealpilot.api")

settings = get_settings()
store = make_store(settings.database_url, settings.embed_dim)
searcher = HybridSearcher(store, HashingEmbedder(settings.embed_dim))
agent = AppealAgent(searcher, settings)

SAMPLES = Path(
    os.environ.get("APPEALPILOT_SAMPLES", Path(__file__).resolve().parents[2] / "samples")
)
MAX_UPLOAD = 15 * 1024 * 1024

app = FastAPI(title="AppealPilot", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def process_case(docs: list[UploadedDoc], today: date | None = None) -> CaseResult:
    case_id = uuid.uuid4().hex[:12]
    for d in docs:
        if d.kind == "policy" and d.text:
            searcher.index(case_id, chunk_policy("policy", d.text))
    state = CaseState(case_id=case_id, docs=docs, today=today or date.today())
    result = agent.run(state)
    store.save_case(case_id, result.model_dump(mode="json"))
    log.info("case %s done in %s mode", case_id, result.mode)
    return result


async def _read(upload: UploadFile, kind: str) -> UploadedDoc:
    data = await upload.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"{upload.filename} is larger than 15 MB")
    name = upload.filename or kind
    return UploadedDoc(name=name, kind=kind, text=extract_text(name, data), data=data)


@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "version": __version__,
        "mode": "claude" if settings.anthropic_api_key else "offline",
        "store": type(store).__name__,
    }


@app.post("/api/cases", response_model=CaseResult)
async def create_case(
    policy: UploadFile = File(..., description="Policy wording (PDF or text)"),
    denial: UploadFile | None = File(None, description="Denial / repudiation letter"),
    denial_text: str | None = Form(None, description="Or paste the denial letter text"),
    supporting: list[UploadFile] = File(default_factory=list),
) -> CaseResult:
    if denial is None and not denial_text:
        raise HTTPException(422, "Upload the denial letter or paste its text")
    docs = [await _read(policy, "policy")]
    if denial is not None:
        docs.append(await _read(denial, "denial"))
    else:
        docs.append(UploadedDoc(name="denial.txt", kind="denial", text=denial_text or ""))
    for f in supporting:
        docs.append(await _read(f, "supporting"))
    return process_case(docs)


@app.post("/api/demo", response_model=CaseResult)
def demo_case() -> CaseResult:
    """Run the bundled sample case (a pre-existing-disease denial) end to end."""
    docs = [
        UploadedDoc("policy_wording.txt", "policy", (SAMPLES / "policy_wording.txt").read_text()),
        UploadedDoc("denial_letter.txt", "denial", (SAMPLES / "denial_letter.txt").read_text()),
        UploadedDoc(
            "discharge_summary.txt", "supporting", (SAMPLES / "discharge_summary.txt").read_text()
        ),
    ]
    return process_case(docs)


def _get(case_id: str) -> dict:
    data = store.get_case(case_id)
    if data is None:
        raise HTTPException(404, "case not found")
    return data


@app.get("/api/cases/{case_id}", response_model=CaseResult)
def get_case(case_id: str) -> dict:
    return _get(case_id)


@app.get("/api/cases/{case_id}/letter.txt", response_class=PlainTextResponse)
def letter(case_id: str) -> str:
    appeal = _get(case_id).get("appeal") or {}
    return appeal.get("body", "")


@app.get("/api/cases/{case_id}/deadlines.ics")
def deadlines_ics(case_id: str) -> Response:
    data = _get(case_id)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AppealPilot//EN"]
    for d in data.get("deadlines", []):
        day = d["due"].replace("-", "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{case_id}-{d['step']}@appealpilot",
            f"DTSTART;VALUE=DATE:{day}",
            f"SUMMARY:AppealPilot: {d['step'].replace('_', ' ')}",
            f"DESCRIPTION:{d['description']}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines), media_type="text/calendar")


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str) -> dict:
    if not store.delete_case(case_id):
        raise HTTPException(404, "case not found")
    return {"deleted": case_id}
