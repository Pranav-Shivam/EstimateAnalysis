"""Phase 7 done-when, backend half: with the demo dataset seeded, three quotes sit flagged in the queue and one is
blocked by the guardrails; correcting the three and replaying leaves each with a second, clean estimate and no
open review item, and the guardrail-blocked quote untouched.

What is bypassed, deliberately: the three LLM clients (scripted stand-ins in scripts/demo/fakes.py), and the
procrastinate queue (the replay consolidates inline, as the worker would). Everything else is production code,
run against the real Phase 1 dataset loaded into this test's transaction."""
import json
from datetime import datetime

from app.estimate.constant import DATASET_AS_OF
from app.estimate.models import EstimateDraftRow
from app.metrics.service import compute_metrics
from app.quotes.service import get_quote_detail, list_quotes
from demo.scenarios import _needed, select_cases
from demo.seed import pending_replays, replay, seed, seed_remaining
from load_data import DATA_DIR, load_all
from tests.graph_support import build_reader


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def test_seeded_flags_are_cleared_by_corrections_and_the_replay(db_session, graph_client, graph_ns):
    load_all(db_session)
    build_reader(db_session, graph_client, graph_ns)
    scenarios, catalog = _load("scenarios.json"), _load("catalog.json")
    cases = select_cases(db_session, scenarios, catalog, DATASET_AS_OF)
    corrections_before = compute_metrics(db_session).counts

    seeded = seed(db_session, graph_client, graph_ns, cases, scenarios)

    by_role = {s.case.role: s for s in seeded}
    assert {s.case.role for s in seeded} == {c.role for c in cases}
    assert by_role["price_gap"].review_dimension == "price_provenance"
    assert by_role["graph_gap"].review_dimension == "graph_completion"
    assert by_role["contract_gap"].review_dimension == "contract_discount"
    assert by_role["blocked"].review_dimension == "guardrail"
    assert all(by_role[role].trusted for role in ("clean", "discontinued", "duplicate_b", "revision_b"))
    assert pending_replays(db_session) == []

    replayed = replay(db_session, graph_client, graph_ns, cases)

    assert {r.case_id for r in replayed} == {by_role[r].case.case_id for r in ("price_gap", "graph_gap", "contract_gap")}
    for role in ("price_gap", "graph_gap", "contract_gap"):
        detail = get_quote_detail(db_session, by_role[role].quote_request_id)
        assert len(detail.estimates) == 2
        # Rows made in this one transaction share a created_at, so tell the two estimates apart by id, not order.
        oldest = next(e for e in detail.estimates if e.estimate_id == by_role[role].estimate_id)
        newest = next(e for e in detail.estimates if e.estimate_id != by_role[role].estimate_id)
        assert oldest.judge_verdict.trusted is False
        assert oldest.review_items[0].status == "consolidated"
        assert newest.judge_verdict.trusted is True
        assert newest.review_items == []
    blocked = get_quote_detail(db_session, by_role["blocked"].quote_request_id)
    assert len(blocked.estimates) == 1
    assert blocked.estimates[0].review_items[0].status == "open"

    # One transaction gives every estimate the same created_at, so pin the first estimates as the older ones.
    for role in ("price_gap", "graph_gap", "contract_gap"):
        db_session.get(EstimateDraftRow, by_role[role].estimate_id).created_at = datetime(2020, 1, 1)
    db_session.flush()
    assert replay(db_session, graph_client, graph_ns) == []
    summaries = {s.quote_request_id: s for s in list_quotes(db_session)}
    assert summaries[by_role["price_gap"].quote_request_id].open_review_items == 0
    corrections_after = compute_metrics(db_session).counts
    assert corrections_after.review_items_corrected - corrections_before.review_items_corrected == 3


def test_replay_stays_flagged_when_consolidation_wrote_nothing(db_session, graph_client, graph_ns, monkeypatch):
    load_all(db_session)
    build_reader(db_session, graph_client, graph_ns)
    scenarios, catalog = _load("scenarios.json"), _load("catalog.json")
    cases = select_cases(db_session, scenarios, catalog, DATASET_AS_OF)
    seed(db_session, graph_client, graph_ns, cases, scenarios)
    monkeypatch.setattr("demo.seed.consolidate_review_item", lambda *args, **kwargs: None)

    replayed = {r.case_id: r for r in replay(db_session, graph_client, graph_ns, cases)}

    by_role = {c.role: c.case_id for c in cases}
    assert replayed[by_role["graph_gap"]].trusted is False
    assert replayed[by_role["contract_gap"]].trusted is False


def test_planted_gaps_touch_no_other_selected_case(db_session):
    load_all(db_session)
    scenarios, catalog = _load("scenarios.json"), _load("catalog.json")
    requires = {sku["sku_id"]: sku["requires"] for sku in catalog}

    cases = select_cases(db_session, scenarios, catalog, DATASET_AS_OF)

    def footprint(case):
        entities = case.scenario["entities"]
        return set(_needed(requires, entities.get("sku_ids") or [entities["sku_id"]]))

    gaps = [c for c in cases if c.price_gap or c.graph_gap]
    planted = {c.price_gap for c in gaps if c.price_gap} | {sku for c in gaps if c.graph_gap for sku in c.graph_gap}
    for case in cases:
        if case not in gaps:
            assert footprint(case).isdisjoint(planted), f"{case.role} shares a planted SKU"


def test_seed_remaining_brings_every_scenario_into_the_app(db_session, graph_client, graph_ns):
    load_all(db_session)
    build_reader(db_session, graph_client, graph_ns)
    scenarios, catalog = _load("scenarios.json"), _load("catalog.json")
    cases = select_cases(db_session, scenarios, catalog, DATASET_AS_OF)
    seed(db_session, graph_client, graph_ns, cases, scenarios)

    added = seed_remaining(db_session, graph_client, graph_ns, cases, scenarios)

    assert added == len(scenarios) - len(cases)
    assert {q.case_id for q in list_quotes(db_session)} == {s["case_id"] for s in scenarios}
    assert seed_remaining(db_session, graph_client, graph_ns, cases, scenarios) == 0
