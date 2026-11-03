"""Agent loop tests with a scripted fake Claude client (no network, no key)."""

from datetime import date
from types import SimpleNamespace as NS

from appealpilot.agent import AppealAgent
from appealpilot.config import Settings
from appealpilot.documents import UploadedDoc
from appealpilot.tools import CaseState


def _tool(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def _resp(stop, content):
    return NS(
        stop_reason=stop,
        content=content,
        usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
    )


class FakeClient:
    """Plays back a fixed sequence of model turns and records what it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return self.turns.pop(0)


DENIAL = {
    "insurer": "Suraksha General Insurance Ltd.",
    "claim_number": "SGI/HC/2026/884213",
    "denial_date": "2026-10-12",
    "amount_claimed": 184500,
    "amount_paid": None,
    "category": "pre_existing_disease",
    "reason_text": "history of gall bladder stones since 2021",
    "clauses_cited_by_insurer": ["4.1"],
    "diagnosis": "cholelithiasis",
}


def _scripted_turns(first_quote):
    good = "diagnosed by a physician not more than 36 months prior to the date of commencement"
    letter = lambda q: {  # noqa: E731
        "subject": "Appeal against rejection of claim SGI/HC/2026/884213",
        "body": "Dear Grievance Officer, ...",
        "citations": [{"clause_id": "policy:2.3", "quote": q, "argument": "Not a PED."}],
        "requested_relief": "Settle in full",
    }
    return [
        _resp("tool_use", [_tool("t1", "extract_denial", DENIAL)]),
        _resp(
            "tool_use",
            [
                _tool("t2", "search_policy", {"query": "pre-existing disease definition", "k": 3}),
                _tool("t3", "check_documents", {"category": "pre_existing_disease"}),
            ],
        ),
        _resp("tool_use", [_tool("t4", "draft_letter", letter(first_quote))]),
        _resp("tool_use", [_tool("t5", "draft_letter", letter(good))]),
        _resp(
            "tool_use",
            [
                _tool(
                    "t6",
                    "schedule_deadline",
                    {"denial_date": "2026-10-12", "grievance_filed": None},
                )
            ],
        ),
        _resp("end_turn", [NS(type="text", text="Done.")]),
    ]


def _state(policy_text, denial_text):
    docs = [
        UploadedDoc("policy.txt", "policy", policy_text),
        UploadedDoc("denial.txt", "denial", denial_text),
    ]
    return CaseState("c1", docs=docs, today=date(2026, 11, 3))


def test_agent_recovers_from_ungrounded_citation(searcher, policy_text, denial_text):
    fake = FakeClient(_scripted_turns("the policy covers every illness"))
    agent = AppealAgent(searcher, Settings(anthropic_api_key="test"), client=fake)
    result = agent.run(_state(policy_text, denial_text))

    assert result.mode == "claude"
    assert result.appeal.citations[0].clause_id == "policy:2.3"
    assert result.deadlines and result.documents
    # The rejected draft came back to the model as an error tool_result.
    # messages: user, then (assistant, tool results) per turn; turn 3 is the rejected draft.
    retry_msg = fake.calls[3]["messages"][6]["content"][0]
    assert retry_msg["is_error"] is True and "not found verbatim" in retry_msg["content"]
    assert result.usage["turns"] == 6
    # Untrusted documents are fenced, and the request carries the model settings.
    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert '<document kind="denial"' in first["messages"][0]["content"][1]["text"]
    assert first["fallbacks"] == "default"


def test_agent_fills_gaps_when_model_stops_early(searcher, policy_text, denial_text):
    fake = FakeClient([_resp("end_turn", [NS(type="text", text="I can't help.")])])
    agent = AppealAgent(searcher, Settings(anthropic_api_key="test"), client=fake)
    result = agent.run(_state(policy_text, denial_text))
    assert result.appeal is not None and result.deadlines


def test_agent_falls_back_offline_on_api_error(searcher, policy_text, denial_text):
    class Boom:
        beta = NS(messages=NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("503"))))

    agent = AppealAgent(searcher, Settings(anthropic_api_key="test"), client=Boom())
    result = agent.run(_state(policy_text, denial_text))
    assert result.mode == "offline"
    assert result.appeal.citations
