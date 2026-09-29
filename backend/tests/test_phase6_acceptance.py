"""Phase 6 done-when: a planted correction becomes a permanent reference fact, and the identical scenario later
passes without a review item, once per judge dimension.

What is bypassed, deliberately: the judge's model (an evidence-reactive fake stands in for Claude Haiku; the
evidence it reads is built by production code) and the queue (consolidate_review_item runs inline, as the worker
would run it). The real queue path, route to procrastinate to worker, is covered by
tests/app/consolidation/test_queue_smoke.py."""
from sqlalchemy import select

from app.consolidation.service import consolidate_review_item
from app.estimate.guardrails import check_contract_discount, graph_is_current
from app.estimate.schemas import EstimateDraft
from app.estimate.service import run_estimate
from app.intake.repository import save_quote_request
from app.judge.models import ReviewItemRow
from app.judge.service import resolve_review_item, run_judge
from app.reference_data.models import Contract, Sku, SkuRequirement
from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore
from core.tracing.langfuse_client import TracingClient
from tests.app.estimate.fakes import ScriptedLLM, submit_turn
from tests.app.estimate.seed import AS_OF, seed_world
from tests.graph_support import FakeEmbedder, graph_edge_count, graph_node

GAP_SKU = "SKU-E-GAP"
PREDICTED_PRICE = 20.0  # median of the three priced peers in Cat-E-P (10, 20, 30)
CORRECTED_PRICE = 42.5


class EvidenceReactiveJudge:
    """Scripted stand-in for the Claude Haiku judge that reacts to the real, deterministic evidence handed to it:
    it doubts price provenance whenever any line's price was predicted and is satisfied by a list price. The
    evidence is built by production code; only the model's reading of it is faked, so no LLM call is made."""

    def __init__(self) -> None:
        self.evidence_seen: list[list[dict]] = []

    def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore:
        self.evidence_seen.append(evidence)
        predicted = any(line["price"]["price_source"] == "predicted" for line in evidence)
        return RawJudgeScore(dimensions=[
            RawDimensionScore(
                name="price_provenance", score=0.2 if predicted else 0.95,
                rationale="price is a peer-median prediction" if predicted else "price is the reference list price",
            ),
            RawDimensionScore(name="contract_discount", score=1.0, rationale="no discount claimed"),
            RawDimensionScore(name="graph_completion", score=0.9, rationale="live SKU, no required parts"),
        ])


def _quote_request(session, sku_ids):
    return save_quote_request(
        session, raw_email_text=f"need one each of {', '.join(sku_ids)}",
        parsed_json={"resolved_line_items": [
            {"sku_name_as_written": sku_id, "sku_id": sku_id, "quantity": "1"} for sku_id in sku_ids
        ]},
        content_fingerprint={"sku_ids": list(sku_ids)}, style_fingerprint={"tokens": []},
        customer_id="CUST-E1", contract_id="CTR-E1",
    )


def _line(sku_id, unit_price, price_source="list", discount_pct=0.0):
    return {"sku_id": sku_id, "quantity": 1, "unit_price": unit_price, "price_source": price_source,
            "discount_pct": discount_pct}


def _draft(lines):
    return {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": lines}


def _estimate_and_judge(session, reader, judge, draft):
    request = _quote_request(session, [line["sku_id"] for line in draft["lines"]])
    estimate = run_estimate(
        session, request.id, AS_OF, ScriptedLLM([submit_turn(draft)]), reader, FakeEmbedder(), TracingClient(None),
    )
    assert estimate.result.status == "ready"
    return run_judge(session, reader, AS_OF, estimate.row.id, judge), estimate.row.id


def _review_items_for(session, estimate_id):
    return session.scalars(select(ReviewItemRow).where(ReviewItemRow.estimate_id == estimate_id)).all()


def _resolve_and_consolidate(session, graph_client, graph_ns, review_item_id, correction):
    """What the resolve route and then the worker do, inline: the route flushes the resolution, the worker
    consolidates it."""
    resolution = resolve_review_item(session, review_item_id, "corrected", correction)
    session.flush()
    assert resolution.consolidation_required is True
    consolidate_review_item(session, graph_client, graph_ns, review_item_id)
    session.flush()


def test_a_planted_price_correction_becomes_a_permanent_fact_and_the_same_scenario_skips_review(
    db_session, graph_client, graph_ns, make_reader,
):
    seed_world(db_session)
    reader = make_reader()
    judge = EvidenceReactiveJudge()

    # First run: the SKU has no list price, so the agent quotes a prediction and the judge escalates it.
    first, first_estimate_id = _estimate_and_judge(
        db_session, reader, judge, _draft([_line(GAP_SKU, PREDICTED_PRICE, "predicted")]),
    )
    assert first.verdict.trusted is False
    assert first.review_item.dimension == "price_provenance"
    assert judge.evidence_seen[0][0]["price"]["price_source"] == "predicted"
    assert db_session.get(Sku, GAP_SKU).list_price is None
    (open_item,) = _review_items_for(db_session, first_estimate_id)
    assert open_item.status == "open"

    # A reviewer corrects the predicted price.
    _resolve_and_consolidate(
        db_session, graph_client, graph_ns, open_item.id, {"sku_id": GAP_SKU, "corrected_unit_price": CORRECTED_PRICE},
    )

    # The correction is now reference data and a graph property, and the graph still matches Postgres.
    assert open_item.status == "consolidated"
    assert db_session.get(Sku, GAP_SKU).list_price == CORRECTED_PRICE
    assert graph_node(graph_client, graph_ns, GAP_SKU)["props"]["list_price"] == CORRECTED_PRICE
    assert graph_is_current(db_session, reader) is True

    # Identical scenario again: the price now comes from the reference list, so the judge has nothing to doubt.
    second, second_estimate_id = _estimate_and_judge(
        db_session, reader, judge, _draft([_line(GAP_SKU, CORRECTED_PRICE)]),
    )
    second_line_evidence = judge.evidence_seen[1][0]["price"]
    assert second_line_evidence["price_source"] == "list"
    assert second_line_evidence["list_price"] == CORRECTED_PRICE
    assert second.verdict.trusted is True
    assert second.review_item is None
    assert _review_items_for(db_session, second_estimate_id) == []


NEEDS_PART_SKU = "SKU-E-P2"
REQUIRED_PART_SKU = "SKU-E-P3"


class RequiredPartReactiveJudge:
    """Doubts graph completion for SKU-E-P2 while the graph records no required part for it (the reviewer knows it
    needs SKU-E-P3, which the reference data lacks), and is satisfied once a required part is recorded and none is
    missing from the draft. Reads the real graph evidence; only the model's reading is faked."""

    def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore:
        graph = [line["graph"] for line in evidence if line["sku_id"] == NEEDS_PART_SKU]
        doubtful = any(not g["required_part_ids"] or g["missing_required_part_ids"] for g in graph)
        return RawJudgeScore(dimensions=[
            RawDimensionScore(name="price_provenance", score=0.95, rationale="list prices"),
            RawDimensionScore(name="contract_discount", score=1.0, rationale="no discount claimed"),
            RawDimensionScore(
                name="graph_completion", score=0.2 if doubtful else 0.9,
                rationale="SKU-E-P2 usually ships with a part the graph does not record" if doubtful
                else "required parts recorded and quoted",
            ),
        ])


def test_a_planted_required_part_becomes_a_graph_edge_and_the_same_scenario_skips_review(
    db_session, graph_client, graph_ns, make_reader,
):
    seed_world(db_session)
    reader = make_reader()
    judge = RequiredPartReactiveJudge()
    draft = _draft([_line(NEEDS_PART_SKU, 20.0), _line(REQUIRED_PART_SKU, 30.0)])

    # First run: the graph records no required part for SKU-E-P2, so the judge escalates graph completion.
    first, first_estimate_id = _estimate_and_judge(db_session, reader, judge, draft)
    assert first.verdict.trusted is False
    assert first.review_item.dimension == "graph_completion"
    assert reader.required_parts(NEEDS_PART_SKU) == []
    (open_item,) = _review_items_for(db_session, first_estimate_id)

    # A reviewer confirms SKU-E-P2 requires SKU-E-P3.
    _resolve_and_consolidate(
        db_session, graph_client, graph_ns, open_item.id,
        {"sku_id": NEEDS_PART_SKU, "required_sku_id": REQUIRED_PART_SKU},
    )

    # The correction is now a SkuRequirement row and a REQUIRES edge, and the graph still matches Postgres.
    assert open_item.status == "consolidated"
    assert db_session.get(SkuRequirement, (NEEDS_PART_SKU, REQUIRED_PART_SKU)) is not None
    assert graph_edge_count(graph_client, graph_ns, NEEDS_PART_SKU, "REQUIRES", REQUIRED_PART_SKU) == 1
    assert graph_is_current(db_session, reader) is True

    # Identical scenario again: the requirement is recorded and quoted, so the judge has nothing to doubt.
    second, second_estimate_id = _estimate_and_judge(db_session, reader, judge, draft)
    assert second.verdict.trusted is True
    assert second.review_item is None
    assert _review_items_for(db_session, second_estimate_id) == []


UNCOVERED_SKU = "SKU-E-P1"
UNCOVERED_CATEGORY = "Cat-E-P"
CONTRACT_DISCOUNT = 10.0


class CoverageReactiveJudge:
    """Doubts the contract dimension when a contract customer's SKU-E-P1 line carries no discount (was Cat-E-P
    really left out of the contract?), and is satisfied once the discount is claimed on a line the graph shows the
    contract covering. Reads the real contract evidence; only the model's reading is faked."""

    def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore:
        contract = [line["contract"] for line in evidence if line["sku_id"] == UNCOVERED_SKU]
        doubtful = any(c["discount_pct"] == 0 or c["covered"] is not True for c in contract)
        return RawJudgeScore(dimensions=[
            RawDimensionScore(name="price_provenance", score=0.95, rationale="list price"),
            RawDimensionScore(
                name="contract_discount", score=0.2 if doubtful else 0.95,
                rationale="contract customer quoted without a discount on Cat-E-P" if doubtful
                else "discount matches a covering, active contract",
            ),
            RawDimensionScore(name="graph_completion", score=0.9, rationale="live SKU, no required parts"),
        ])


def test_a_planted_contract_coverage_becomes_a_covers_edge_and_the_same_scenario_skips_review(
    db_session, graph_client, graph_ns, make_reader,
):
    seed_world(db_session)
    reader = make_reader()
    judge = CoverageReactiveJudge()
    discounted = _draft([_line(UNCOVERED_SKU, 10.0, discount_pct=CONTRACT_DISCOUNT)])

    # Before: the contract does not cover Cat-E-P, so the discount guardrail refuses a discounted line and the
    # agent can only quote it at full price, which the judge escalates.
    assert check_contract_discount(db_session, EstimateDraft.model_validate(discounted), AS_OF, "CUST-E1") != []
    first, first_estimate_id = _estimate_and_judge(db_session, reader, judge, _draft([_line(UNCOVERED_SKU, 10.0)]))
    assert first.verdict.trusted is False
    assert first.review_item.dimension == "contract_discount"
    (open_item,) = _review_items_for(db_session, first_estimate_id)

    # A reviewer confirms CTR-E1 does cover Cat-E-P.
    _resolve_and_consolidate(
        db_session, graph_client, graph_ns, open_item.id, {"contract_id": "CTR-E1", "category": UNCOVERED_CATEGORY},
    )

    # The correction is now contract coverage and a COVERS edge, and the graph still matches Postgres.
    assert open_item.status == "consolidated"
    assert UNCOVERED_CATEGORY in db_session.get(Contract, "CTR-E1").covered_categories
    assert graph_edge_count(graph_client, graph_ns, "CTR-E1", "COVERS", UNCOVERED_CATEGORY) == 1
    assert graph_is_current(db_session, reader) is True
    assert check_contract_discount(db_session, EstimateDraft.model_validate(discounted), AS_OF, "CUST-E1") == []

    # Identical scenario again: the discount is now allowed and covered, so the judge has nothing to doubt.
    second, second_estimate_id = _estimate_and_judge(db_session, reader, judge, discounted)
    assert second.verdict.trusted is True
    assert second.review_item is None
    assert _review_items_for(db_session, second_estimate_id) == []
