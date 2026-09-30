import pytest

from app.intake.repository import save_quote_request
from demo.fakes import (
    DemoJudgeClient, DemoSetupError, ScriptedAgentClient, ScriptedExtractionClient, UnusedEmbedder, blocked_draft,
    build_draft,
)
from tests.app.estimate.seed import AS_OF, seed_world


def _request(session, sku_ids, customer_id="CUST-E1", contract_id="CTR-E1"):
    return save_quote_request(
        session, raw_email_text="x",
        parsed_json={"resolved_line_items": [
            {"sku_name_as_written": s, "sku_id": s, "quantity": "1"} for s in sku_ids
        ]},
        content_fingerprint={}, style_fingerprint={}, customer_id=customer_id, contract_id=contract_id,
    )


def test_extraction_reads_the_scenario_ground_truth():
    scenario = {
        "case_id": "sc-1", "customer": {"name": "Zenith Contractors", "contact": "Suresh Iyer"},
        "entities": {"customer_id": "CUST-1", "sku_names": ["Alpha", "Beta"]}, "email_text": "hello",
    }

    result = ScriptedExtractionClient([scenario]).extract_quote_request("hello")

    assert result.customer_name_as_written == "Zenith Contractors"
    assert [i.sku_name_as_written for i in result.line_items] == ["Alpha", "Beta"]
    assert result.raw_text == "hello"


def test_extraction_handles_a_single_sku_scenario():
    scenario = {
        "case_id": "sc-1", "customer": {"name": "Z", "contact": "C"},
        "entities": {"customer_id": "CUST-1", "sku_name": "Alpha"}, "email_text": "hello",
    }

    result = ScriptedExtractionClient([scenario]).extract_quote_request("hello")

    assert [i.sku_name_as_written for i in result.line_items] == ["Alpha"]


def test_draft_adds_required_parts_and_applies_the_covered_contract_discount(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-B1"])

    draft = build_draft(db_session, reader, request, AS_OF)

    assert [line["sku_id"] for line in draft["lines"]] == ["SKU-E-B1", "SKU-E-A1"]
    by_sku = {line["sku_id"]: line for line in draft["lines"]}
    assert by_sku["SKU-E-A1"]["discount_pct"] == 10.0
    assert by_sku["SKU-E-B1"]["discount_pct"] == 0.0
    assert draft["contract_id"] == "CTR-E1"
    assert [a["kind"] for a in draft["adjustments"]] == ["added_required"]


def test_draft_substitutes_a_discontinued_sku(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-OLD"])

    draft = build_draft(db_session, reader, request, AS_OF)

    assert [line["sku_id"] for line in draft["lines"]] == ["SKU-E-A1"]
    assert draft["adjustments"][0]["kind"] == "substituted"


def test_draft_predicts_the_price_of_a_sku_with_no_list_price(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-GAP"], customer_id="CUST-E2", contract_id=None)

    draft = build_draft(db_session, reader, request, AS_OF)

    assert draft["lines"][0]["unit_price"] == 20.0
    assert draft["lines"][0]["price_source"] == "predicted"
    assert draft["contract_id"] is None
    assert draft["lines"][0]["discount_pct"] == 0.0


def test_draft_refuses_a_sku_whose_price_cannot_be_predicted(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-LONE"], customer_id="CUST-E2", contract_id=None)

    with pytest.raises(DemoSetupError):
        build_draft(db_session, reader, request, AS_OF)


def test_blocked_draft_zeroes_only_the_first_quantity():
    draft = {"lines": [{"sku_id": "A", "quantity": 1}, {"sku_id": "B", "quantity": 1}], "adjustments": []}

    blocked = blocked_draft(draft)

    assert [line["quantity"] for line in blocked["lines"]] == [0, 1]
    assert draft["lines"][0]["quantity"] == 1


def test_scripted_agent_submits_the_same_draft_every_turn():
    draft = {"customer_id": "CUST-1", "lines": []}
    client = ScriptedAgentClient(draft)

    first = client.next_turn([], [])
    second = client.next_turn([], [])

    assert first.tool_calls[0].name == "submit_draft"
    assert first.tool_calls[0].arguments == draft
    assert second.tool_calls[0].arguments == draft


def _evidence(sku_id, *, price_source="list", required=(), contract_id=None, discount=0.0):
    return {
        "line_index": 0, "sku_id": sku_id, "unit_price": 10.0,
        "price": {"price_source": price_source},
        "contract": {"contract_id": contract_id, "discount_pct": discount},
        "graph": {"required_part_ids": list(required), "missing_required_part_ids": []},
    }


def _scores(judge, evidence):
    return {d.name: d.score for d in judge.score(evidence, "prompt").dimensions}


def test_judge_trusts_clean_evidence():
    scores = _scores(DemoJudgeClient(set(), set()), [_evidence("A")])

    assert min(scores.values()) > 0.8


def test_judge_doubts_a_predicted_price():
    scores = _scores(DemoJudgeClient(set(), set()), [_evidence("A", price_source="predicted")])

    assert scores["price_provenance"] < 0.5


def test_judge_doubts_a_watched_sku_with_no_recorded_required_part():
    judge = DemoJudgeClient({"A"}, set())

    assert _scores(judge, [_evidence("A")])["graph_completion"] < 0.5
    assert _scores(judge, [_evidence("A", required=["B"])])["graph_completion"] > 0.8


def test_judge_doubts_a_watched_contract_line_at_full_price():
    judge = DemoJudgeClient(set(), {"A"})

    assert _scores(judge, [_evidence("A", contract_id="CTR-1")])["contract_discount"] < 0.5
    assert _scores(judge, [_evidence("A", contract_id="CTR-1", discount=10.0)])["contract_discount"] > 0.8
    assert _scores(judge, [_evidence("A")])["contract_discount"] > 0.8


def test_unused_embedder_fails_loudly():
    with pytest.raises(DemoSetupError):
        UnusedEmbedder().embed(["anything"])
