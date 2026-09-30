import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from scripts.live_run.meter import BudgetExceeded, UsageMeter, metered_openai
from scripts.live_run.scoring import (
    CORRECT, CORRECT_FLAGGED, SAFE_ESCALATION, WRONG_ESCALATION, WRONG_READY, DraftView, Expectation, classify_outcome, dedupe_pairs,
    score_extraction,
)


class FakeOpenAI:
    def __init__(self) -> None:
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=200, input_tokens=500, output_tokens=100)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(usage=usage)))
        self.responses = SimpleNamespace(parse=lambda **kw: SimpleNamespace(usage=usage))
        self.embeddings = SimpleNamespace(create=lambda **kw: SimpleNamespace(usage=usage))


def test_meter_prices_each_stage_from_its_own_usage_fields():
    meter = UsageMeter(cap_usd=5.0)
    client = metered_openai(FakeOpenAI(), meter)
    client.chat.completions.create(model="gpt-4o", messages=[])
    client.responses.parse(model="gpt-4o", input=[])
    client.embeddings.create(model="text-embedding-3-small", input=["x"])
    assert meter.stages["agent"].usd == pytest.approx((1000 * 2.5 + 200 * 10) / 1e6)
    assert meter.stages["extraction"].input_tokens == 500
    assert meter.stages["embedding"].output_tokens == 0
    assert meter.stages["embedding"].usd == pytest.approx(1000 * 0.02 / 1e6)


def test_meter_refuses_the_next_call_once_the_cap_is_reached():
    meter = UsageMeter(cap_usd=0.004)
    client = metered_openai(FakeOpenAI(), meter)
    client.chat.completions.create(model="gpt-4o", messages=[])
    with pytest.raises(BudgetExceeded):
        client.chat.completions.create(model="gpt-4o", messages=[])
    assert meter.stages["agent"].calls == 1


def test_extraction_score_compares_customer_and_sku_set():
    entities = {"customer_id": "CUST-1", "sku_ids": ["A", "B"]}
    assert score_extraction(entities, "CUST-1", ["B", "A"]) == {"customer_ok": True, "skus_ok": True}
    assert score_extraction(entities, None, ["A"]) == {"customer_ok": False, "skus_ok": False}
    assert score_extraction({"customer_id": "C", "sku_id": "A"}, "C", ["A"])["skus_ok"] is True


def test_ready_draft_with_every_expected_sku_is_correct():
    view = DraftView("ready", {"LIVE": 0.0, "PART": 0.0})
    assert classify_outcome(view, Expectation(present=frozenset({"LIVE", "PART"}))) == CORRECT


def test_ready_draft_missing_a_required_part_is_wrong_ready():
    view = DraftView("ready", {"LIVE": 0.0})
    assert classify_outcome(view, Expectation(present=frozenset({"LIVE", "PART"}))) == WRONG_READY


def test_ready_draft_keeping_a_discontinued_sku_is_wrong_ready():
    view = DraftView("ready", {"OLD": 0.0, "LIVE": 0.0})
    expectation = Expectation(present=frozenset({"LIVE"}), forbidden=frozenset({"OLD"}))
    assert classify_outcome(view, expectation) == WRONG_READY


def test_discount_on_an_uncovered_sku_is_wrong_ready():
    view = DraftView("ready", {"CONDUIT": 10.0})
    expectation = Expectation(present=frozenset({"CONDUIT"}), no_discount=frozenset({"CONDUIT"}))
    assert classify_outcome(view, expectation) == WRONG_READY


def test_review_is_safe_only_when_the_case_could_not_be_finished():
    view = DraftView("needs_review")
    assert classify_outcome(view, Expectation(present=frozenset({"A"}))) == WRONG_ESCALATION
    assert classify_outcome(view, Expectation(present=frozenset(), achievable=False)) == SAFE_ESCALATION
    assert classify_outcome(DraftView("ready", {"A": 0.0}), Expectation(present=frozenset(), achievable=False)) == WRONG_READY


def test_dedupe_pairs_put_the_later_email_against_the_earlier_one():
    scenarios = [
        {"case_id": "sc-2", "scenario_type": "duplicate_pair", "entities": {"pair_id": "dup-1"}},
        {"case_id": "sc-1", "scenario_type": "duplicate_pair", "entities": {"pair_id": "dup-1"}},
        {"case_id": "sc-4", "scenario_type": "revision_pair", "entities": {"pair_id": "rev-1"}},
        {"case_id": "sc-3", "scenario_type": "revision_pair", "entities": {"pair_id": "rev-1"}},
        {"case_id": "sc-9", "scenario_type": "clean_distinct", "entities": {}},
    ]
    assert dedupe_pairs(scenarios) == [("sc-2", "sc-1", "DUPLICATE_OF"), ("sc-4", "sc-3", "REVISION_OF")]


def test_expectation_follows_replacement_and_required_parts(db_session):
    from scripts.live_run.expectation import build_expectation
    from tests.app.estimate.seed import seed_world

    seed_world(db_session)
    swap = build_expectation(db_session, {"scenario_type": "discontinued_swap", "entities": {"sku_id": "SKU-E-OLD"}})
    assert swap.present == frozenset({"SKU-E-A1"}) and swap.forbidden == frozenset({"SKU-E-OLD"})
    needs_part = build_expectation(
        db_session, {"scenario_type": "missing_required_part", "entities": {"sku_id": "SKU-E-B1"}},
    )
    assert needs_part.present == frozenset({"SKU-E-A1", "SKU-E-B1"}) and needs_part.achievable
    mismatch = build_expectation(
        db_session, {"scenario_type": "discount_category_mismatch", "entities": {"sku_id": "SKU-E-B1"}},
    )
    assert mismatch.no_discount == frozenset({"SKU-E-B1"})


def test_expectation_is_unachievable_when_no_live_replacement_exists(db_session):
    from app.reference_data.repository import upsert_sku
    from scripts.live_run.expectation import build_expectation

    upsert_sku(
        db_session, sku_id="SKU-DEAD", name="Dead End", category="Cat", list_price=1.0, discontinued=True,
        replaced_by=None, in_stock=False,
    )
    db_session.flush()
    result = build_expectation(db_session, {"scenario_type": "discontinued_swap", "entities": {"sku_id": "SKU-DEAD"}})
    assert not result.achievable


def test_flagged_review_with_the_right_draft_is_correct_flagged_and_a_wrong_draft_is_not():
    expectation = Expectation(present=frozenset({"LIVE"}))
    assert classify_outcome(DraftView("needs_review", {"LIVE": 0.0}, flagged=True), expectation) == CORRECT_FLAGGED
    assert classify_outcome(DraftView("needs_review", {"OTHER": 0.0}, flagged=True), expectation) == WRONG_ESCALATION
    assert classify_outcome(DraftView("needs_review", {"LIVE": 0.0}, flagged=False), expectation) == WRONG_ESCALATION
