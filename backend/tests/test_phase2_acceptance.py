import json
from pathlib import Path

from app.intake.repository import save_quote_request
from app.dedupe.service import run_dedupe
from load_data import load_catalog, load_customers

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_reference_data(session):
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8"))

    load_catalog(session, catalog)
    load_customers(session, customers)
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
        others = [v for v in verdicts if v.candidate_quote_request_id != rows_by_case_id[case_ids[0]].id]
        assert all(v.verdict == "DISTINCT" for v in others)

    for case_ids in revision_pairs.values():
        assert len(case_ids) == 2
        revision_row = rows_by_case_id[case_ids[1]]
        verdicts = run_dedupe(db_session, revision_row.id)
        matched = [v for v in verdicts if v.candidate_quote_request_id == rows_by_case_id[case_ids[0]].id]
        assert len(matched) == 1
        assert matched[0].verdict == "REVISION_OF"
        others = [v for v in verdicts if v.candidate_quote_request_id != rows_by_case_id[case_ids[0]].id]
        assert all(v.verdict == "DISTINCT" for v in others)

    non_pair_types = {"discontinued_swap", "missing_required_part", "discount_category_mismatch", "clean_distinct"}
    non_pair_cases = [c for c in scenarios if c["scenario_type"] in non_pair_types]
    for case in non_pair_cases:
        row = rows_by_case_id[case["case_id"]]
        verdicts = run_dedupe(db_session, row.id)
        assert all(v.verdict == "DISTINCT" for v in verdicts)
