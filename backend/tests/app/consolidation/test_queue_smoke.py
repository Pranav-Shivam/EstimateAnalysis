"""The real queue path, end to end against local Postgres: the procrastinate schema from migration 0007, the API
opening the app in its lifespan, a real .defer(), and a real worker run. Every other consolidation test swaps in
an in-memory connector or calls the service directly, which is exactly what hid a worker that could not start and
a route that could not enqueue.

The worker and the route open their own connections, so these rows must be committed. Everything is namespaced
by a random suffix and deleted afterwards, and the worker only listens to a queue named for this test, so a job
anyone else deferred is never picked up."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.consolidation.tasks import app as consolidation_app, consolidate_review_item_task, run_worker
from app.estimate.models import EstimateDraftRow
from app.estimate.repository import save_estimate_draft
from app.intake.models import QuoteRequestRow
from app.intake.repository import save_quote_request
from app.judge.models import EvalCaseRow, JudgeVerdictRow, ReviewItemRow
from app.judge.repository import save_judge_verdict, save_review_item
from app.judge.service import resolve_review_item
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_sku
from core.db.session import make_engine, make_session_factory
from main import app
from tests.conftest import TEST_DATABASE_URL

CORRECTED_PRICE = 42.5
JOBS_FOR_ITEM = "SELECT task_name, queue_name, status FROM procrastinate_jobs WHERE args->>'review_item_id' = :id"


@pytest.fixture
def committed_session():
    engine = make_engine(TEST_DATABASE_URL)
    session = make_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def committed_review_item(committed_session):
    session = committed_session
    suffix = uuid.uuid4().hex[:12]
    sku_id = f"SKU-SMOKE-{suffix}"
    upsert_sku(
        session, sku_id=sku_id, name=f"Smoke test part {suffix}", category=f"Cat-SMOKE-{suffix}", list_price=None,
        discontinued=False, replaced_by=None, in_stock=True,
    )
    request = save_quote_request(
        session, raw_email_text="smoke", parsed_json={"resolved_line_items": []}, content_fingerprint={},
        style_fingerprint={}, customer_id=None,
    )
    estimate = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[], iterations=1,
        reason=None,
    )
    verdict = save_judge_verdict(
        session, estimate_id=estimate.id, model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension="price_provenance", trusted=False,
    )
    item = save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=estimate.id, dimension="price_provenance",
        fact="price is a peer-median prediction",
        evidence={"lines": [{"line_index": 0, "sku_id": sku_id, "price_source": "predicted"}]}, line_index=0,
    )
    item_id = item.id
    session.commit()
    try:
        yield item_id, sku_id
    finally:
        session.rollback()
        session.execute(text("DELETE FROM procrastinate_jobs WHERE args->>'review_item_id' = :id"), {"id": str(item_id)})
        session.execute(delete(EvalCaseRow).where(EvalCaseRow.source_review_item_id == item_id))
        session.execute(delete(ReviewItemRow).where(ReviewItemRow.id == item_id))
        session.execute(delete(JudgeVerdictRow).where(JudgeVerdictRow.id == verdict.id))
        session.execute(delete(EstimateDraftRow).where(EstimateDraftRow.id == estimate.id))
        session.execute(delete(QuoteRequestRow).where(QuoteRequestRow.id == request.id))
        session.execute(delete(Sku).where(Sku.sku_id == sku_id))
        session.commit()


def test_the_api_opens_the_queue_and_a_corrected_resolve_enqueues_a_real_job(committed_review_item, committed_session):
    item_id, sku_id = committed_review_item

    # The context manager runs the lifespan, which is what opens the procrastinate app in a real API process.
    with TestClient(app) as client:
        response = client.post(f"/v1/review/{item_id}/resolve", json={
            "outcome": "corrected", "correction": {"sku_id": sku_id, "corrected_unit_price": CORRECTED_PRICE},
        })

    assert response.status_code == 200
    assert response.json()["consolidation_enqueued"] is True
    jobs = committed_session.execute(text(JOBS_FOR_ITEM), {"id": str(item_id)}).all()
    assert [(job.task_name, job.status) for job in jobs] == [("consolidate_review_item", "todo")]


def test_a_worker_runs_a_deferred_consolidation_job_to_completion(committed_review_item, committed_session, graph_client):
    item_id, sku_id = committed_review_item
    resolve_review_item(
        committed_session, item_id, "corrected", {"sku_id": sku_id, "corrected_unit_price": CORRECTED_PRICE},
    )
    committed_session.commit()
    queue = f"smoke-{uuid.uuid4().hex[:12]}"

    with consolidation_app.open():
        consolidate_review_item_task.configure(queue=queue).defer(review_item_id=str(item_id))
    run_worker(queues=[queue], wait=False, install_signal_handlers=False, listen_notify=False)

    committed_session.expire_all()
    assert committed_session.get(ReviewItemRow, item_id).status == "consolidated"
    assert committed_session.get(Sku, sku_id).list_price == CORRECTED_PRICE
    jobs = committed_session.execute(text(JOBS_FOR_ITEM), {"id": str(item_id)}).all()
    assert [(job.queue_name, job.status) for job in jobs] == [(queue, "succeeded")]
