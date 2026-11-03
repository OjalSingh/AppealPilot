from fastapi.testclient import TestClient

from appealpilot.api import app

client = TestClient(app)


def test_health():
    assert client.get("/healthz").json()["ok"] is True


def test_demo_end_to_end_and_delete():
    r = client.post("/api/demo")
    assert r.status_code == 200
    body = r.json()
    cid = body["case_id"]
    assert body["denial"]["category"] == "pre_existing_disease"
    assert body["appeal"]["citations"]

    assert "Grievance Redressal Officer" in client.get(f"/api/cases/{cid}/letter.txt").text
    ics = client.get(f"/api/cases/{cid}/deadlines.ics").text
    assert ics.startswith("BEGIN:VCALENDAR") and "ombudsman" in ics

    assert client.delete(f"/api/cases/{cid}").status_code == 200
    assert client.get(f"/api/cases/{cid}").status_code == 404


def test_upload_with_pasted_denial(policy_text):
    r = client.post(
        "/api/cases",
        files={"policy": ("policy.txt", policy_text.encode(), "text/plain")},
        data={
            "denial_text": "Reason for rejection: room rent exceeded, proportionate deduction applied on medicines."
        },
    )
    assert r.status_code == 200
    assert r.json()["denial"]["category"] == "room_rent_limit"
    assert "policy:6.2" in [c["clause_id"] for c in r.json()["appeal"]["citations"]]


def test_denial_is_required(policy_text):
    r = client.post("/api/cases", files={"policy": ("p.txt", policy_text.encode(), "text/plain")})
    assert r.status_code == 422
