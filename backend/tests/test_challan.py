from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from appealpilot.api import app
from appealpilot.challan import (
    CHALLAN_TOOL_DEFS,
    ChallanAgent,
    ChallanFacts,
    ChallanState,
    ChallanToolbox,
    assess,
    build_challan_deadlines,
    infer_claims,
    parse_challan,
    rule_clauses,
)
from appealpilot.config import Settings
from appealpilot.documents import UploadedDoc
from appealpilot.redact import redact
from appealpilot.retrieval import HybridSearcher, InMemoryStore
from appealpilot.schemas import Challan, Ground

SAMPLE = (Path(__file__).resolve().parents[2] / "samples" / "challan_notice.txt").read_text()
client = TestClient(app)


def _searcher():
    s = HybridSearcher(InMemoryStore())
    s.index("c1", rule_clauses())
    return s


def _ch(**kw):
    base = dict(offence_date=date(2026, 6, 10), notice_date=date(2026, 6, 20), is_echallan=True)
    return Challan(**{**base, **kw})


def test_parse_sample_notice():
    ch = parse_challan(SAMPLE)
    assert ch.challan_number == "SC2606108842"
    assert ch.vehicle_number == "MH12AB1234"
    assert ch.offence_date == date(2026, 6, 10) and ch.notice_date == date(2026, 9, 22)
    assert ch.amount == 2000 and ch.section == "112/183"
    assert ch.is_echallan


def test_late_notice_is_strong_and_within_window_is_not():
    late, _ = assess(_ch(notice_date=date(2026, 9, 22)), ChallanFacts())
    assert [(f.ground, f.strength) for f in late] == [(Ground.NOTICE_TIME_BARRED, "strong")]
    ok, notes = assess(_ch(), ChallanFacts(claims=[Ground.NOTICE_TIME_BARRED]))
    assert ok == [] and any("inside the 15-day window" in n for n in notes)


def test_exactly_fifteen_days_is_in_time():
    findings, _ = assess(_ch(notice_date=date(2026, 6, 25)), ChallanFacts())
    assert findings == []


def test_spot_challan_does_not_get_time_bar():
    findings, notes = assess(_ch(notice_date=date(2026, 9, 22), is_echallan=False), ChallanFacts())
    assert findings == [] and any("on-the-spot" in n for n in notes)


def test_missing_dates_gives_possible_only():
    findings, notes = assess(Challan(), ChallanFacts(claims=[Ground.NOTICE_TIME_BARRED]))
    assert findings[0].strength == "possible" and any("Enter both" in n for n in notes)


def test_user_grounds_are_possible_never_strong():
    findings, _ = assess(_ch(), ChallanFacts(claims=[Ground.WRONG_VEHICLE, Ground.ALREADY_PAID]))
    assert {f.strength for f in findings} == {"possible"}
    assert all(f.evidence_needed for f in findings)


def test_sale_date_after_offence_is_ignored():
    findings, notes = assess(_ch(), ChallanFacts(sold_date=date(2026, 7, 1)))
    assert findings == [] and any("sale date after" in n for n in notes)
    findings, _ = assess(_ch(), ChallanFacts(sold_date=date(2026, 5, 1)))
    assert findings[0].ground is Ground.VEHICLE_SOLD


def test_infer_claims_from_notes():
    got = infer_claims(
        "I sold the car in May and never received any SMS. The photo is of a different vehicle"
    )
    assert {Ground.VEHICLE_SOLD, Ground.NO_NOTICE_RECEIVED, Ground.WRONG_VEHICLE} <= set(got)


def test_deadlines_never_invent_a_legal_window():
    with_date = {
        d.step: d.due for d in build_challan_deadlines(date(2026, 11, 20), today=date(2026, 11, 4))
    }
    assert with_date["pay_or_contest_by"] == date(2026, 11, 20)
    assert with_date["file_grievance"] == date(2026, 11, 17)
    without = build_challan_deadlines(None, today=date(2026, 11, 4))
    assert [d.step for d in without] == ["find_notice_deadline"]


def test_toolbox_only_lets_rule_clauses_be_cited():
    tb = ChallanToolbox(ChallanState("c1", docs=[]), _searcher())
    base = dict(subject="s", body="b", requested_relief="cancel")
    quote = "The notice of offence shall be sent within fifteen days"
    assert tb.draft_representation(
        **base, citations=[{"clause_id": "rule:1.1", "quote": quote, "argument": "x"}]
    ) == {"ok": True}
    bad = tb.draft_representation(
        **base, citations=[{"clause_id": "guide:2.3", "quote": "File a grievance", "argument": "x"}]
    )
    assert bad["ok"] is False and "only 'rule:'" in bad["errors"][0]
    fake = tb.draft_representation(
        **base, citations=[{"clause_id": "rule:1.1", "quote": "within 90 days", "argument": "x"}]
    )
    assert fake["ok"] is False
    assert tb.draft_representation(**base, citations=[]) == {"ok": True}


def test_offline_agent_end_to_end():
    text = SAMPLE
    state = ChallanState(
        "c1",
        [UploadedDoc("n.txt", "challan", text)],
        ChallanFacts(pay_by=date(2026, 11, 20)),
        today=date(2026, 11, 4),
    )
    r = ChallanAgent(_searcher()).run(state)
    assert r.mode == "offline" and r.kind == "challan"
    assert r.findings[0].ground is Ground.NOTICE_TIME_BARRED
    assert r.appeal.citations[0].clause_id == "rule:1.1"
    assert "104 days" in r.appeal.body
    assert {d.step for d in r.deadlines} == {"file_grievance", "pay_or_contest_by"}


def _tool(i, name, inp):
    return NS(type="tool_use", id=i, name=name, input=inp)


def _resp(stop, content):
    return NS(
        stop_reason=stop,
        content=content,
        usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
    )


def test_claude_agent_loop_with_scripted_model():
    chal = dict(
        challan_number="X1",
        vehicle_number="MH12AB1234",
        offence="speeding",
        section=None,
        offence_date="2026-06-10",
        notice_date="2026-09-22",
        amount=2000,
        location=None,
        authority=None,
        is_echallan=True,
    )
    turns = [
        _resp("tool_use", [_tool("1", "extract_challan", chal)]),
        _resp(
            "tool_use",
            [
                _tool("2", "search_rules", {"query": "notice time limit", "k": 3}),
                _tool("3", "assess_grounds", {"claims": ["notice_time_barred"]}),
            ],
        ),
        _resp(
            "tool_use",
            [
                _tool(
                    "4",
                    "draft_representation",
                    dict(
                        subject="s",
                        body="Dear ...",
                        requested_relief="cancel",
                        citations=[
                            {
                                "clause_id": "rule:1.1",
                                "quote": "within ninety days",
                                "argument": "x",
                            }
                        ],
                    ),
                )
            ],
        ),
        _resp(
            "tool_use",
            [
                _tool(
                    "5",
                    "draft_representation",
                    dict(
                        subject="s",
                        body="Dear ...",
                        requested_relief="cancel",
                        citations=[
                            {
                                "clause_id": "rule:1.1",
                                "quote": "shall be sent within fifteen days",
                                "argument": "late",
                            }
                        ],
                    ),
                )
            ],
        ),
        _resp(
            "tool_use",
            [_tool("6", "schedule_deadlines", {"pay_by": "2026-11-20", "hearing_date": None})],
        ),
        _resp("end_turn", [NS(type="text", text="Done.")]),
    ]
    calls = []

    def create(**kw):
        calls.append(kw)
        return turns.pop(0)

    fake = NS(beta=NS(messages=NS(create=create)))
    state = ChallanState("c1", [UploadedDoc("n.txt", "challan", "x")], today=date(2026, 11, 4))
    r = ChallanAgent(_searcher(), Settings(anthropic_api_key="t"), client=fake).run(state)
    assert r.mode == "claude" and r.usage["turns"] == 6
    assert r.appeal.body == "Dear ..."  # the model's own letter, once its citation was grounded
    assert calls[3]["messages"][6]["content"][0]["is_error"] is True
    assert calls[0]["tools"] == CHALLAN_TOOL_DEFS


def test_api_demo_and_delete():
    r = client.post("/api/demo/challan")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "challan" and body["denial"] is None
    assert body["findings"][0]["ground"] == "notice_time_barred"
    cid = body["case_id"]
    assert "ombudsman" not in client.get(f"/api/cases/{cid}/deadlines.ics").text
    assert client.delete(f"/api/cases/{cid}").status_code == 200


def test_api_upload_with_user_grounds():
    r = client.post(
        "/api/challans",
        data={
            "challan_text": "Challan No: ZZ123456\nVehicle No: DL1CAB1234\nOffence: Signal jumping\nDate of offence: 01/10/2026\nChallan date: 05/10/2026\nFine: Rs 1,000",
            "grounds": ["wrong_vehicle"],
            "notes": "The photo is of a different car",
            "pay_by": "2026-11-30",
        },
    )
    assert r.status_code == 200
    f = r.json()["findings"]
    assert [x["ground"] for x in f] == ["wrong_vehicle"] and f[0]["strength"] == "possible"


def test_api_validation():
    assert client.post("/api/challans", data={}).status_code == 422
    bad = client.post("/api/challans", data={"challan_text": "x", "pay_by": "tomorrow"})
    assert bad.status_code == 422
    assert (
        client.post("/api/challans", data={"challan_text": "x", "grounds": ["nope"]}).status_code
        == 422
    )


def test_vehicle_numbers_are_redacted():
    assert "MH12AB1234" not in redact("Vehicle MH12AB1234 was seen")
