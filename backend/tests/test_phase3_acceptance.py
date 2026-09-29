import json
from pathlib import Path

from app.estimate.constant import DATASET_AS_OF
from app.estimate.pricing import predict_price_for_sku
from app.estimate.service import run_estimate
from app.estimate.tools import get_related_parts
from app.intake.repository import save_quote_request
from app.reference_data.repository import all_customers, all_skus, contracts_for_customer, get_sku, required_sku_ids
from load_data import load_catalog, load_customers, load_pricing
from tests.app.estimate.fakes import ScriptedLLM, submit_turn
from tests.graph_support import FakeEmbedder, make_ctx

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_world(session):
    load_catalog(session, json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8")))
    load_customers(session, json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8")))
    session.flush()
    pricing = json.loads((DATA_DIR / "pricing.json").read_text(encoding="utf-8"))
    load_pricing(session, pricing)
    session.flush()
    return pricing


def _scenarios(scenario_type):
    scenarios = json.loads((DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))
    return [s for s in scenarios if s["scenario_type"] == scenario_type]


def _quote_request(session, case, sku_id=None):
    entities = case["entities"]
    resolved_sku_id = sku_id or entities["sku_id"]
    return save_quote_request(
        session, raw_email_text=case["email_text"],
        parsed_json={"resolved_line_items": [{"sku_name_as_written": entities["sku_name"],
                                              "sku_id": resolved_sku_id, "quantity": "1"}]},
        content_fingerprint={"sku_ids": [resolved_sku_id]}, style_fingerprint={"tokens": []},
        customer_id=entities["customer_id"], contract_id=entities["contract_id"], case_id=case["case_id"],
    )


def _with_required_parts(session, sku_id):
    """The SKU and every part it needs, transitively, in a stable order."""
    ordered, queue = [], [sku_id]
    while queue:
        current = queue.pop(0)
        if current not in ordered:
            ordered.append(current)
            queue.extend(required_sku_ids(session, current))
    return ordered


def _draft_with_discount(session, case, discount_pct):
    entities = case["entities"]
    lines = []
    for position, sku_id in enumerate(_with_required_parts(session, entities["sku_id"])):
        sku = get_sku(session, sku_id)
        lines.append({"sku_id": sku.sku_id, "quantity": 1, "unit_price": sku.list_price, "price_source": "list",
                      "discount_pct": discount_pct if position == 0 else 0.0})
    return {"customer_id": entities["customer_id"], "contract_id": entities["contract_id"], "lines": lines}


def test_every_planted_bad_discount_is_blocked_and_ends_needs_review(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _scenarios("discount_category_mismatch")
    assert len(cases) == 10

    for case in cases:
        contract = contracts_for_customer(db_session, case["entities"]["customer_id"])[0]
        sku = get_sku(db_session, case["entities"]["sku_id"])
        assert sku.category not in contract.covered_categories
        assert contract.effective_from <= DATASET_AS_OF <= contract.effective_to

        request = _quote_request(db_session, case)
        bad = _draft_with_discount(db_session, case, contract.discount_pct)
        llm = ScriptedLLM([submit_turn(bad, call_id=f"c{i}") for i in range(4)])

        run = run_estimate(db_session, request.id, DATASET_AS_OF, llm, graph, FakeEmbedder())

        assert run.result.status == "needs_review", case["case_id"]
        assert run.result.violations[0].guardrail == "contract_discount", case["case_id"]
        assert "not covered" in run.result.violations[0].message, case["case_id"]


def test_a_draft_borrowing_another_customers_covering_contract_never_ends_ready(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    case = _scenarios("discount_category_mismatch")[0]
    entities = case["entities"]
    category = get_sku(db_session, entities["sku_id"]).category
    donor, donor_contract = next(
        (customer, contract)
        for customer in all_customers(db_session) if customer.customer_id != entities["customer_id"]
        for contract in contracts_for_customer(db_session, customer.customer_id)
        if category in contract.covered_categories and contract.effective_from <= DATASET_AS_OF <= contract.effective_to
    )
    request = _quote_request(db_session, case)
    borrowed = _draft_with_discount(db_session, case, donor_contract.discount_pct)
    borrowed["customer_id"] = donor.customer_id
    borrowed["contract_id"] = donor_contract.contract_id
    llm = ScriptedLLM([submit_turn(borrowed, call_id=f"c{i}") for i in range(4)])

    run = run_estimate(db_session, request.id, DATASET_AS_OF, llm, graph, FakeEmbedder())

    assert run.result.status == "needs_review"
    assert run.result.violations[0].guardrail == "customer_identity"


def test_every_planted_bad_discount_passes_once_the_discount_is_removed(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()

    for case in _scenarios("discount_category_mismatch"):
        contract = contracts_for_customer(db_session, case["entities"]["customer_id"])[0]
        request = _quote_request(db_session, case)
        turns = [
            submit_turn(_draft_with_discount(db_session, case, contract.discount_pct)),
            submit_turn(_draft_with_discount(db_session, case, 0.0), call_id="call-2"),
        ]

        run = run_estimate(db_session, request.id, DATASET_AS_OF, ScriptedLLM(turns), graph, FakeEmbedder())

        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]


def test_discount_on_a_covered_category_is_allowed_for_the_same_customers(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()

    for case in _scenarios("discount_category_mismatch"):
        contract = contracts_for_customer(db_session, case["entities"]["customer_id"])[0]
        covered_sku = next(
            s for s in all_skus(db_session)
            if s.category in contract.covered_categories and s.list_price is not None and not s.discontinued
            and not required_sku_ids(db_session, s.sku_id)
        )
        entities = case["entities"]
        draft = {
            "customer_id": entities["customer_id"], "contract_id": contract.contract_id,
            "lines": [{"sku_id": covered_sku.sku_id, "quantity": 1, "unit_price": covered_sku.list_price,
                       "price_source": "list", "discount_pct": contract.discount_pct}],
        }
        request = _quote_request(db_session, case, sku_id=covered_sku.sku_id)

        run = run_estimate(db_session, request.id, DATASET_AS_OF, ScriptedLLM([submit_turn(draft)]), graph, FakeEmbedder())

        assert run.result.status == "ready", case["case_id"]


def test_discontinued_swap_cases_expose_a_live_replacement_to_the_agent(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    ctx = make_ctx(db_session, graph, as_of=DATASET_AS_OF)

    for case in _scenarios("discontinued_swap"):
        related = get_related_parts(ctx, sku_id=case["entities"]["sku_id"])

        assert related["replacement"] is not None, case["case_id"]
        assert related["replacement"]["discontinued"] is False, case["case_id"]


def test_missing_required_part_cases_expose_the_required_parts_to_the_agent(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    ctx = make_ctx(db_session, graph, as_of=DATASET_AS_OF)

    for case in _scenarios("missing_required_part"):
        related = get_related_parts(ctx, sku_id=case["entities"]["sku_id"])

        assert related["required_parts"], case["case_id"]


def test_every_price_book_gap_sku_can_be_predicted_and_scenario_skus_are_priced(db_session):
    pricing = _load_world(db_session)

    for sku_id in pricing["gap_sku_ids"]:
        sku = get_sku(db_session, sku_id)
        assert sku.list_price is None
        assert predict_price_for_sku(db_session, sku) is not None, sku_id

    for scenario_type in ("discontinued_swap", "missing_required_part", "discount_category_mismatch"):
        for case in _scenarios(scenario_type):
            assert get_sku(db_session, case["entities"]["sku_id"]).list_price is not None, case["case_id"]
