from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import PEER_MIN
from app.intake.resolution import resolve_extraction
from app.reference_data.repository import (
    contracts_for_customer, get_sku, required_sku_ids, skus_with_list_price_in_category,
)
from demo.fakes import DemoSetupError, ScriptedExtractionClient

MAX_REPLACEMENT_HOPS = 10


@dataclass(frozen=True)
class DemoCase:
    role: str
    scenario: dict
    # "trusted", "flagged:<judge dimension>" or "guardrail"
    expectation: str
    # What a reviewer would submit to resolve the flag, in the exact shape POST /v1/review/{id}/resolve takes.
    correction: dict | None = None
    # The (sku_id, required_sku_id) requirement removed from the reference data to plant the knowledge gap.
    graph_gap: tuple[str, str] | None = None
    # The SKU whose list price is removed to plant the pricing gap. The dataset's own unpriced SKUs appear in no
    # scenario, so a scenario SKU is unpriced here instead.
    price_gap: str | None = None

    @property
    def case_id(self) -> str:
        return self.scenario["case_id"]


def _sku_ids(scenario: dict) -> list[str]:
    entities = scenario["entities"]
    return entities.get("sku_ids") or [entities["sku_id"]]


def _resolves(session: Session, scenario: dict) -> bool:
    """Whether intake, run on this scenario, lands on exactly the customer and SKUs the ground truth names."""
    extraction = ScriptedExtractionClient([scenario]).extract_quote_request(scenario["email_text"])
    resolved = resolve_extraction(session, extraction)
    return (
        resolved.customer_id == scenario["entities"]["customer_id"]
        and [item.sku_id for item in resolved.line_items] == _sku_ids(scenario)
    )


def _priced_and_live(session: Session, sku_id: str) -> bool:
    sku = get_sku(session, sku_id)
    return sku is not None and sku.list_price is not None and not sku.discontinued


def _needed(requires: dict[str, list[str]], sku_ids: list[str]) -> list[str]:
    """The SKUs plus every part they transitively require, which is what a correct draft has to quote."""
    found: list[str] = []
    pending = list(sku_ids)
    while pending:
        sku_id = pending.pop(0)
        if sku_id not in found:
            found.append(sku_id)
            pending.extend(requires.get(sku_id, []))
    return found


def _all_priced_and_live(session: Session, requires: dict[str, list[str]], sku_ids: list[str]) -> bool:
    return all(_priced_and_live(session, sku_id) for sku_id in _needed(requires, sku_ids))


def _live_replacement(session: Session, sku_id: str) -> str | None:
    sku = get_sku(session, sku_id)
    for _ in range(MAX_REPLACEMENT_HOPS):
        if sku is None:
            return None
        if not sku.discontinued:
            return sku.sku_id
        sku = get_sku(session, sku.replaced_by) if sku.replaced_by else None
    return None


def _pairs(scenarios: list[dict], scenario_type: str) -> list[tuple[dict, dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for scenario in scenarios:
        if scenario["scenario_type"] == scenario_type:
            grouped[scenario["entities"]["pair_id"]].append(scenario)
    return [tuple(sorted(members, key=lambda s: s["case_id"])) for members in grouped.values() if len(members) == 2]


def select_cases(session: Session, scenarios: list[dict], catalog: list[dict], as_of: date) -> list[DemoCase]:
    """Picks one scenario per demo role from the dataset, reading only reference data. A role that no scenario can
    fill raises DemoSetupError: the demo must not quietly run with a story missing."""
    requires = {sku["sku_id"]: sku["requires"] for sku in catalog}
    by_type: dict[str, list[dict]] = defaultdict(list)
    for scenario in scenarios:
        by_type[scenario["scenario_type"]].append(scenario)
    used: set[str] = set()
    # SKUs the planted gaps touch. No other case may quote them, or its own outcome would change.
    reserved: set[str] = set()

    def pick(role: str, candidates: list[dict], accepts) -> dict:
        for scenario in candidates:
            if (
                scenario["case_id"] not in used and _resolves(session, scenario) and accepts(scenario)
                and _footprint(scenario).isdisjoint(reserved)
            ):
                used.add(scenario["case_id"])
                return scenario
        raise DemoSetupError(f"no scenario in the dataset can play the {role!r} role")

    def _footprint(scenario: dict) -> set[str]:
        ids = [scenario["entities"].get("sku_id")] if "sku_id" in scenario["entities"] else _sku_ids(scenario)
        live = [_live_replacement(session, sku_id) or sku_id for sku_id in ids]
        return set(_needed(requires, ids + live))

    def clean(scenario: dict) -> bool:
        return _all_priced_and_live(session, requires, _sku_ids(scenario))

    def price_gap(scenario: dict) -> bool:
        """A clean scenario whose first SKU can lose its list price and still get a peer-median prediction."""
        sku = get_sku(session, _sku_ids(scenario)[0])
        peers = [peer for peer in skus_with_list_price_in_category(session, sku.category) if peer.sku_id != sku.sku_id]
        return clean(scenario) and len(peers) >= PEER_MIN

    def graph_gap(scenario: dict) -> bool:
        sku_id = scenario["entities"]["sku_id"]
        required = requires[sku_id]
        return (
            len(required) == 1 and required_sku_ids(session, sku_id) == required
            and _all_priced_and_live(session, requires, [sku_id])
        )

    def contract_gap(scenario: dict) -> bool:
        entities = scenario["entities"]
        contracts = contracts_for_customer(session, entities["customer_id"])
        if len(contracts) != 1 or contracts[0].contract_id != entities["contract_id"]:
            return False
        contract, sku = contracts[0], get_sku(session, entities["sku_id"])
        return (
            _all_priced_and_live(session, requires, [sku.sku_id])
            and sku.category == entities["sku_category"] and sku.category not in contract.covered_categories
            and contract.discount_pct > 0 and contract.effective_from <= as_of <= contract.effective_to
        )

    def discontinued(scenario: dict) -> bool:
        live_id = _live_replacement(session, scenario["entities"]["sku_id"])
        sku = get_sku(session, scenario["entities"]["sku_id"])
        return sku.discontinued and live_id is not None and _all_priced_and_live(session, requires, [live_id])

    def pair_role(role_a: str, role_b: str, scenario_type: str) -> list[DemoCase]:
        for first, second in _pairs(scenarios, scenario_type):
            if (
                first["case_id"] not in used and second["case_id"] not in used
                and _resolves(session, first) and _resolves(session, second)
                and clean(first) and clean(second)
                and _footprint(first).isdisjoint(reserved) and _footprint(second).isdisjoint(reserved)
            ):
                used.update((first["case_id"], second["case_id"]))
                return [DemoCase(role_a, first, "trusted"), DemoCase(role_b, second, "trusted")]
        raise DemoSetupError(f"no {scenario_type} in the dataset can play the {role_a!r} and {role_b!r} roles")

    clean_scenarios = by_type["clean_distinct"]
    priced = pick("price_gap", clean_scenarios, price_gap)
    gap_sku_id = _sku_ids(priced)[0]
    missing = pick("graph_gap", by_type["missing_required_part"], graph_gap)
    missing_sku_id = missing["entities"]["sku_id"]
    reserved.update(_footprint(priced) | _footprint(missing))
    first_clean = pick("clean", clean_scenarios, clean)
    second_clean = pick("clean", clean_scenarios, clean)
    swap = pick("discontinued", by_type["discontinued_swap"], discontinued)
    mismatch = pick("contract_gap", by_type["discount_category_mismatch"], contract_gap)
    blocked = pick("blocked", clean_scenarios, clean)

    return [
        DemoCase("clean", first_clean, "trusted"),
        DemoCase("clean", second_clean, "trusted"),
        DemoCase("discontinued", swap, "trusted"),
        DemoCase(
            "price_gap", priced, "flagged:price_provenance",
            correction={"sku_id": gap_sku_id, "corrected_unit_price": get_sku(session, gap_sku_id).list_price},
            price_gap=gap_sku_id,
        ),
        DemoCase(
            "graph_gap", missing, "flagged:graph_completion",
            correction={"sku_id": missing_sku_id, "required_sku_id": requires[missing_sku_id][0]},
            graph_gap=(missing_sku_id, requires[missing_sku_id][0]),
        ),
        DemoCase(
            "contract_gap", mismatch, "flagged:contract_discount",
            correction={
                "contract_id": mismatch["entities"]["contract_id"], "category": mismatch["entities"]["sku_category"],
            },
        ),
        *pair_role("duplicate_a", "duplicate_b", "duplicate_pair"),
        *pair_role("revision_a", "revision_b", "revision_pair"),
        DemoCase("blocked", blocked, "guardrail"),
    ]
