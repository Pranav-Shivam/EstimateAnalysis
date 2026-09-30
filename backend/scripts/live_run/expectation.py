"""What a correct draft must contain for a scenario, worked out straight from Postgres so the answer key never
depends on the knowledge graph the agent is being tested against."""
from sqlalchemy.orm import Session

from app.graph.constant import MAX_CHAIN_HOPS
from app.reference_data.repository import get_sku, required_sku_ids
from scripts.live_run.scoring import Expectation, requested_sku_ids


def _live_end(session: Session, sku_id: str) -> str | None:
    current = get_sku(session, sku_id)
    for _ in range(MAX_CHAIN_HOPS + 1):
        if current is None:
            return None
        if not current.discontinued:
            return current.sku_id
        current = get_sku(session, current.replaced_by) if current.replaced_by else None
    return None


def build_expectation(session: Session, scenario: dict) -> Expectation:
    present: set[str] = set()
    forbidden: set[str] = set()
    achievable = True
    queue = requested_sku_ids(scenario["entities"])
    while queue:
        sku_id = queue.pop()
        live = _live_end(session, sku_id)
        if live is None:
            achievable = False
            continue
        if live != sku_id:
            forbidden.add(sku_id)
        if live not in present:
            present.add(live)
            queue.extend(required_sku_ids(session, live))
    no_discount = (
        frozenset({scenario["entities"]["sku_id"]}) if scenario["scenario_type"] == "discount_category_mismatch"
        else frozenset()
    )
    return Expectation(
        present=frozenset(present), forbidden=frozenset(forbidden), no_discount=no_discount, achievable=achievable,
    )
