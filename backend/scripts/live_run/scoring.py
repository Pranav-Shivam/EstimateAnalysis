"""Scores a live run against the scenario answer key. Pure functions, no I/O."""
from dataclasses import dataclass, field

AGENT_SCENARIO_TYPES = ("discontinued_swap", "missing_required_part", "discount_category_mismatch", "clean_distinct")
EXPECTED_DEDUPE_VERDICT = {"duplicate_pair": "DUPLICATE_OF", "revision_pair": "REVISION_OF"}
CORRECT, CORRECT_FLAGGED, SAFE_ESCALATION, WRONG_READY, WRONG_ESCALATION = (
    "correct", "correct_flagged", "safe_escalation", "wrong_ready", "wrong_escalation",
)


@dataclass(frozen=True)
class Expectation:
    # SKUs that must appear on the draft: the live end of every requested SKU and its transitive required parts.
    present: frozenset[str]
    # Requested SKUs that are discontinued and must not appear.
    forbidden: frozenset[str] = frozenset()
    # SKUs whose contract does not cover their category, so they must carry no discount.
    no_discount: frozenset[str] = frozenset()
    # False when a requested SKU has no live replacement, so the only right answer is a review.
    achievable: bool = True


@dataclass(frozen=True)
class DraftView:
    status: str
    discount_by_sku: dict[str, float] = field(default_factory=dict)
    # True when the draft passed every guardrail and the agent itself asked for a human (for example an
    # out-of-stock replacement, which the system prompt tells it to flag).
    flagged: bool = False

    @property
    def skus(self) -> set[str]:
        return set(self.discount_by_sku)


def requested_sku_ids(entities: dict) -> list[str]:
    return list(entities.get("sku_ids") or [entities["sku_id"]])


def score_extraction(entities: dict, customer_id: str | None, sku_ids: list[str]) -> dict:
    return {
        "customer_ok": customer_id == entities["customer_id"],
        "skus_ok": set(sku_ids) == set(requested_sku_ids(entities)),
    }


def _content_is_right(view: DraftView, expectation: Expectation) -> bool:
    missing = expectation.present - view.skus
    leaked = expectation.forbidden & view.skus
    discounted = {sku for sku in expectation.no_discount if view.discount_by_sku.get(sku, 0.0) > 0}
    return not (missing or leaked or discounted)


def classify_outcome(view: DraftView, expectation: Expectation) -> str:
    """ready and right is correct; ready and wrong is the dangerous one (a wrong draft that would go out without
    a human); a review is safe when the case truly could not be finished, fine when the draft is right and the
    agent flagged it on purpose, and wasteful otherwise."""
    if view.status != "ready":
        if not expectation.achievable:
            return SAFE_ESCALATION
        return CORRECT_FLAGGED if view.flagged and _content_is_right(view, expectation) else WRONG_ESCALATION
    if not expectation.achievable:
        return WRONG_READY
    return CORRECT if _content_is_right(view, expectation) else WRONG_READY


def dedupe_pairs(scenarios: list[dict]) -> list[tuple[str, str, str]]:
    """(later case, earlier case, expected verdict) for every planted pair; the later request is judged against
    the earlier one."""
    by_pair: dict[str, list[dict]] = {}
    for scenario in scenarios:
        if scenario["scenario_type"] in EXPECTED_DEDUPE_VERDICT:
            by_pair.setdefault(scenario["entities"]["pair_id"], []).append(scenario)
    pairs = []
    for members in by_pair.values():
        earlier, later = sorted(members, key=lambda s: s["case_id"])
        pairs.append((later["case_id"], earlier["case_id"], EXPECTED_DEDUPE_VERDICT[later["scenario_type"]]))
    return sorted(pairs)
