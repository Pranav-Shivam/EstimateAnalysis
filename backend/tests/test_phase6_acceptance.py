from sqlalchemy import select

from app.consolidation.service import consolidate_review_item
from app.estimate.guardrails import graph_is_current
from app.estimate.service import run_estimate
from app.intake.repository import save_quote_request
from app.judge.models import ReviewItemRow
from app.judge.service import resolve_review_item, run_judge
from app.reference_data.models import Sku
from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore
from core.tracing.langfuse_client import TracingClient
from tests.app.estimate.fakes import ScriptedLLM, submit_turn
from tests.app.estimate.seed import AS_OF, seed_world
from tests.graph_support import FakeEmbedder, graph_node

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


def _quote_request(session):
    return save_quote_request(
        session, raw_email_text="need one Gapgizmo Prime",
        parsed_json={"resolved_line_items": [{"sku_name_as_written": "Gapgizmo Prime", "sku_id": GAP_SKU, "quantity": "1"}]},
        content_fingerprint={"sku_ids": [GAP_SKU]}, style_fingerprint={"tokens": []},
        customer_id="CUST-E1", contract_id="CTR-E1",
    )


def _draft(unit_price, price_source):
    return {
        "customer_id": "CUST-E1", "contract_id": "CTR-E1",
        "lines": [{"sku_id": GAP_SKU, "quantity": 1, "unit_price": unit_price, "price_source": price_source,
                   "discount_pct": 0.0}],
    }


def _estimate_and_judge(session, reader, judge, draft):
    request = _quote_request(session)
    estimate = run_estimate(
        session, request.id, AS_OF, ScriptedLLM([submit_turn(draft)]), reader, FakeEmbedder(), TracingClient(None),
    )
    assert estimate.result.status == "ready"
    return run_judge(session, reader, AS_OF, estimate.row.id, judge), estimate.row.id


def _review_items_for(session, estimate_id):
    return session.scalars(select(ReviewItemRow).where(ReviewItemRow.estimate_id == estimate_id)).all()


def test_a_planted_price_correction_becomes_a_permanent_fact_and_the_same_scenario_skips_review(
    db_session, graph_client, graph_ns, make_reader,
):
    seed_world(db_session)
    reader = make_reader()
    judge = EvidenceReactiveJudge()

    # First run: the SKU has no list price, so the agent quotes a prediction and the judge escalates it.
    first, first_estimate_id = _estimate_and_judge(db_session, reader, judge, _draft(PREDICTED_PRICE, "predicted"))
    assert first.verdict.trusted is False
    assert first.review_item.dimension == "price_provenance"
    assert judge.evidence_seen[0][0]["price"]["price_source"] == "predicted"
    assert db_session.get(Sku, GAP_SKU).list_price is None
    (open_item,) = _review_items_for(db_session, first_estimate_id)
    assert open_item.status == "open"

    # A reviewer corrects the predicted price; the route flushes the resolution, then the worker consolidates it.
    resolution = resolve_review_item(
        db_session, open_item.id, "corrected", {"sku_id": GAP_SKU, "corrected_unit_price": CORRECTED_PRICE},
    )
    db_session.flush()
    assert resolution.consolidation_required is True
    consolidate_review_item(db_session, graph_client, graph_ns, open_item.id)
    db_session.flush()

    # The correction is now reference data and a graph property, and the graph still matches Postgres.
    assert open_item.status == "consolidated"
    assert db_session.get(Sku, GAP_SKU).list_price == CORRECTED_PRICE
    assert graph_node(graph_client, graph_ns, GAP_SKU)["props"]["list_price"] == CORRECTED_PRICE
    assert graph_is_current(db_session, reader) is True

    # Identical scenario again: the price now comes from the reference list, so the judge has nothing to doubt.
    second, second_estimate_id = _estimate_and_judge(db_session, reader, judge, _draft(CORRECTED_PRICE, "list"))
    second_line_evidence = judge.evidence_seen[1][0]["price"]
    assert second_line_evidence["price_source"] == "list"
    assert second_line_evidence["list_price"] == CORRECTED_PRICE
    assert second.verdict.trusted is True
    assert second.review_item is None
    assert _review_items_for(db_session, second_estimate_id) == []
