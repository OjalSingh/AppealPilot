from datetime import date

from appealpilot.deadlines import build_deadlines
from appealpilot.documents import UploadedDoc, check_documents
from appealpilot.ingest import chunk_policy
from appealpilot.offline import extract_denial
from appealpilot.redact import redact
from appealpilot.schemas import DenialCategory
from appealpilot.tools import CaseState, Toolbox, quote_is_grounded


def test_chunker_keys_clauses_by_number(policy_text):
    ids = {c.id for c in chunk_policy("policy", policy_text)}
    assert {"policy:2.3", "policy:4.1", "policy:6.2", "policy:8.1"} <= ids
    assert "policy:2" not in ids  # bare section headers are dropped


def test_chunker_falls_back_to_paragraphs():
    clauses = chunk_policy("d", "First paragraph here.\n\nSecond paragraph here.")
    assert [c.id for c in clauses] == ["d:p1", "d:p2"]


def test_hybrid_search_finds_contradicting_clause(searcher):
    hits = searcher.search("c1", "proportionate deduction applied to medicines and implants", k=3)
    assert "policy:6.2" in [h.clause.id for h in hits]


def test_cited_clause_number_is_boosted(searcher):
    hits = searcher.search("c1", "not admissible under clause 4.3", k=1)
    assert hits[0].clause.id == "policy:4.3"


def test_extract_denial(denial_text):
    d = extract_denial(denial_text)
    assert d.category is DenialCategory.PRE_EXISTING
    assert d.claim_number == "SGI/HC/2026/884213"
    assert d.denial_date == date(2026, 10, 12)
    assert d.amount_claimed == 184500
    assert "4.1" in d.clauses_cited_by_insurer


def test_quote_grounding():
    text = "The Company shall condone delay in intimation where the delay is proved."
    assert quote_is_grounded("shall condone delay in intimation", text)
    assert quote_is_grounded("The Company shall condone ... is proved", text)
    assert not quote_is_grounded("the Company must always pay", text)


def test_draft_letter_rejects_hallucinated_citation(searcher):
    tools = Toolbox(CaseState("c1", docs=[]), searcher)
    bad = tools.draft_letter(
        subject="s",
        body="b",
        requested_relief="pay",
        citations=[
            {"clause_id": "policy:8.1", "quote": "claims are always payable", "argument": "x"}
        ],
    )
    assert bad["ok"] is False
    unknown = tools.draft_letter(
        subject="s",
        body="b",
        requested_relief="pay",
        citations=[{"clause_id": "policy:99.9", "quote": "anything", "argument": "x"}],
    )
    assert "unknown clause id" in unknown["errors"][0]
    good = tools.draft_letter(
        subject="s",
        body="b",
        requested_relief="pay",
        citations=[
            {
                "clause_id": "policy:8.1",
                "quote": "no claim under this Policy shall be contestable",
                "argument": "x",
            }
        ],
    )
    assert good == {"ok": True}


def test_toolbox_reports_errors_instead_of_raising(searcher):
    tools = Toolbox(CaseState("c1", docs=[]), searcher)
    out, is_error = tools.run("check_documents", {"category": "not_a_category"})
    assert is_error and "error" in out
    out, is_error = tools.run("rm_rf", {})
    assert is_error


def test_document_check_flags_missing_items():
    docs = [
        UploadedDoc("denial.txt", "denial", "repudiation"),
        UploadedDoc("policy.txt", "policy", "policy wording"),
        UploadedDoc("discharge_summary.pdf", "supporting", "Discharge summary ..."),
    ]
    check = check_documents(DenialCategory.NOT_MEDICALLY_NECESSARY, docs)
    assert "Discharge summary" in check.present
    assert "Letter of medical necessity from the treating doctor" in check.missing


def test_deadlines():
    dl = {d.step: d.due for d in build_deadlines(date(2026, 10, 1), date(2026, 10, 5))}
    assert dl["insurer_reply_due"] == date(2026, 10, 19)
    assert dl["ombudsman_eligible"] == date(2026, 11, 4)
    assert dl["ombudsman_last_date"] == date(2027, 10, 1)


def test_large_claim_routes_to_consumer_commission():
    steps = [d.step for d in build_deadlines(date(2026, 10, 1), amount_claimed=6_000_000)]
    assert "consumer_commission" in steps


def test_redaction():
    raw = "Call 9876543210, mail a.b@x.com, Aadhaar 1234 5678 9012, PAN ABCDE1234F"
    out = redact({"t": [raw]})["t"][0]
    for secret in ("9876543210", "a.b@x.com", "1234 5678 9012", "ABCDE1234F"):
        assert secret not in out
