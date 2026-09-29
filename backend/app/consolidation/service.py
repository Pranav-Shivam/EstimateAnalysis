import uuid

from sqlalchemy.orm import Session

from app.graph.service import sync_best_effort, sync_contract_coverage, sync_requirement, sync_sku
from app.judge.repository import lock_review_item
from app.reference_data.repository import (
    add_contract_coverage, reference_fingerprint, set_sku_list_price, upsert_requirement,
)
from core.graph.client import GraphClient


def _consolidate_price_provenance(session: Session, client: GraphClient, ns: str, correction: dict) -> None:
    sku_id = correction["sku_id"]
    set_sku_list_price(session, sku_id, correction["corrected_unit_price"])
    sync_best_effort("sku price correction", sync_sku, session, client, ns, sku_id)


# The two handlers below change reference_fingerprint(). Each reads it before its write, so the graph sync can tell
# whether the graph was current beforehand (see graph.service._advance_graph_meta). Sessions run with autoflush off
# (core/db/session.py), so the write is flushed before the sync reads the post-correction fingerprint.


def _consolidate_graph_completion(session: Session, client: GraphClient, ns: str, correction: dict) -> None:
    sku_id, required_sku_id = correction["sku_id"], correction["required_sku_id"]
    previous_fingerprint = reference_fingerprint(session)
    upsert_requirement(session, sku_id=sku_id, required_sku_id=required_sku_id)
    session.flush()
    sync_best_effort(
        "sku requirement correction", sync_requirement, session, client, ns, sku_id, required_sku_id,
        previous_fingerprint,
    )


def _consolidate_contract_discount(session: Session, client: GraphClient, ns: str, correction: dict) -> None:
    contract_id, category = correction["contract_id"], correction["category"]
    previous_fingerprint = reference_fingerprint(session)
    add_contract_coverage(session, contract_id, category)
    session.flush()
    sync_best_effort(
        "contract coverage correction", sync_contract_coverage, session, client, ns, contract_id, category,
        previous_fingerprint,
    )


_HANDLERS = {
    "price_provenance": _consolidate_price_provenance,
    "graph_completion": _consolidate_graph_completion,
    "contract_discount": _consolidate_contract_discount,
}


def consolidate_review_item(session: Session, client: GraphClient, ns: str, review_item_id: uuid.UUID) -> None:
    row = lock_review_item(session, review_item_id)
    if row is None:
        raise ValueError(f"review item {review_item_id} not found")
    if row.status == "consolidated":
        # A redelivered or redriven job whose earlier run already committed: the fact is written, nothing to do.
        return
    if row.status != "corrected":
        raise ValueError(f"review item {review_item_id} is {row.status!r}, expected 'corrected'")

    handler = _HANDLERS.get(row.dimension)
    if handler is None:
        raise ValueError(f"no consolidation handler for dimension {row.dimension!r}")
    handler(session, client, ns, row.correction)

    row.status = "consolidated"
    session.flush()
