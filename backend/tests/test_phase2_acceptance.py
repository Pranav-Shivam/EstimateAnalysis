import json
from datetime import date
from pathlib import Path

from app.intake.repository import save_quote_request
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_contract, upsert_customer, upsert_site, upsert_sku
from app.dedupe.service import run_dedupe

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_reference_data(session):
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8"))

    for sku in catalog:
        upsert_sku(
            session, sku_id=sku["sku_id"], name=sku["name"], category=sku["category"],
            list_price=sku["list_price"], discontinued=sku["discontinued"], replaced_by=None,
            in_stock=sku["in_stock"],
        )
    session.flush()
    for sku in catalog:
        if sku["discontinued"] and sku["replaced_by"]:
            session.get(Sku, sku["sku_id"]).replaced_by = sku["replaced_by"]

    for customer in customers:
        upsert_customer(session, customer_id=customer["customer_id"], name=customer["name"], account_tier=customer["account_tier"])
        for site in customer["sites"]:
            upsert_site(session, site_id=site["site_id"], customer_id=customer["customer_id"], address=site["address"], zip_code=site["zip"])
        for contract in customer["contracts"]:
            upsert_contract(
                session, contract_id=contract["contract_id"], customer_id=customer["customer_id"],
                discount_category=contract["discount_category"], covered_categories=contract["covered_categories"],
                effective_from=date.fromisoformat(contract["effective_from"]),
                effective_to=date.fromisoformat(contract["effective_to"]),
            )
    session.flush()


def _insert_quote_request(session, case: dict):
    entities = case["entities"]
    if "sku_ids" in entities:
        sku_ids = entities["sku_ids"]
    elif "sku_id" in entities:
        sku_ids = [entities["sku_id"]]
    else:
        sku_ids = []

    return save_quote_request(
        session, raw_email_text=case["email_text"], parsed_json={"case_id": case["case_id"]},
        content_fingerprint={"sku_ids": sorted(set(sku_ids))}, style_fingerprint={"tokens": []},
        customer_id=entities["customer_id"], site_id=entities.get("site_id"), case_id=case["case_id"],
    )


def test_dedupe_classifier_matches_phase1_ground_truth(db_session):
    _load_reference_data(db_session)
    scenarios = json.loads((DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))

    rows_by_case_id = {}
    for case in scenarios:
        rows_by_case_id[case["case_id"]] = _insert_quote_request(db_session, case)
    db_session.flush()

    duplicate_pairs: dict[str, list[str]] = {}
    revision_pairs: dict[str, list[str]] = {}
    for case in scenarios:
        pair_id = case["entities"].get("pair_id")
        if not pair_id:
            continue
        target = duplicate_pairs if case["scenario_type"] == "duplicate_pair" else revision_pairs
        target.setdefault(pair_id, []).append(case["case_id"])

    for case_ids in duplicate_pairs.values():
        assert len(case_ids) == 2
        second_row = rows_by_case_id[case_ids[1]]
        verdicts = run_dedupe(db_session, second_row.id)
        matched = [v for v in verdicts if v.candidate_quote_request_id == rows_by_case_id[case_ids[0]].id]
        assert len(matched) == 1
        assert matched[0].verdict == "DUPLICATE_OF"

    for case_ids in revision_pairs.values():
        assert len(case_ids) == 2
        revision_row = rows_by_case_id[case_ids[1]]
        verdicts = run_dedupe(db_session, revision_row.id)
        matched = [v for v in verdicts if v.candidate_quote_request_id == rows_by_case_id[case_ids[0]].id]
        assert len(matched) == 1
        assert matched[0].verdict == "REVISION_OF"

    clean_distinct_cases = [c for c in scenarios if c["scenario_type"] == "clean_distinct"]
    for case in clean_distinct_cases:
        row = rows_by_case_id[case["case_id"]]
        verdicts = run_dedupe(db_session, row.id)
        assert all(v.verdict == "DISTINCT" for v in verdicts)
