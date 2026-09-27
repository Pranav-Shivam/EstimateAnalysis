from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config
from data_gen.customer_gen import generate_customers
from data_gen.scenario_gen import SCENARIO_TYPES, select_cases


def _dataset():
    config = Config(seed=42, sku_count=650, customer_count=125, scenarios_per_type=10)
    catalog = generate_catalog(config)
    customers = generate_customers(config, catalog)
    return config, catalog, customers


def test_selects_exactly_ten_cases_per_type():
    config, catalog, customers = _dataset()
    cases = select_cases(config, catalog, customers)
    counts = {}
    for case in cases:
        counts[case["scenario_type"]] = counts.get(case["scenario_type"], 0) + 1
    for scenario_type in SCENARIO_TYPES:
        assert counts.get(scenario_type) == 10, f"{scenario_type}: {counts.get(scenario_type)}"


def test_sixty_total_cases_no_duplicate_ids():
    config, catalog, customers = _dataset()
    cases = select_cases(config, catalog, customers)
    assert len(cases) == 60
    case_ids = [c["case_id"] for c in cases]
    assert len(case_ids) == len(set(case_ids))


def test_deterministic_given_same_catalog_and_customers():
    config, catalog, customers = _dataset()
    first = select_cases(config, catalog, customers)
    second = select_cases(config, catalog, customers)
    assert first == second


def test_duplicate_pair_cases_share_entities_except_role():
    config, catalog, customers = _dataset()
    cases = select_cases(config, catalog, customers)
    duplicates = [c for c in cases if c["scenario_type"] == "duplicate_pair"]
    by_pair = {}
    for case in duplicates:
        by_pair.setdefault(case["entities"]["pair_id"], []).append(case)
    for pair_id, pair_cases in by_pair.items():
        assert len(pair_cases) == 2
        roles = {c["entities"]["pair_role"] for c in pair_cases}
        assert roles == {"first", "second"}
        skus = {tuple(c["entities"]["sku_ids"]) for c in pair_cases}
        assert len(skus) == 1, f"pair {pair_id} disagrees on sku_ids"


def test_duplicate_pair_entities_include_sku_names():
    config, catalog, customers = _dataset()
    catalog_by_id = {s["sku_id"]: s for s in catalog}
    cases = select_cases(config, catalog, customers)
    duplicates = [c for c in cases if c["scenario_type"] == "duplicate_pair"]
    assert duplicates
    for case in duplicates:
        sku_names = case["entities"]["sku_names"]
        sku_ids = case["entities"]["sku_ids"]
        assert sku_names == [catalog_by_id[sid]["name"] for sid in sku_ids]


def test_revision_pair_entities_include_sku_names():
    config, catalog, customers = _dataset()
    catalog_by_id = {s["sku_id"]: s for s in catalog}
    cases = select_cases(config, catalog, customers)
    revisions = [c for c in cases if c["scenario_type"] == "revision_pair"]
    assert revisions
    for case in revisions:
        sku_names = case["entities"]["sku_names"]
        sku_ids = case["entities"]["sku_ids"]
        assert sku_names == [catalog_by_id[sid]["name"] for sid in sku_ids]


def test_clean_distinct_entities_include_sku_names():
    config, catalog, customers = _dataset()
    catalog_by_id = {s["sku_id"]: s for s in catalog}
    cases = select_cases(config, catalog, customers)
    clean = [c for c in cases if c["scenario_type"] == "clean_distinct"]
    assert clean
    for case in clean:
        sku_names = case["entities"]["sku_names"]
        sku_ids = case["entities"]["sku_ids"]
        assert sku_names == [catalog_by_id[sid]["name"] for sid in sku_ids]


def test_discount_mismatch_survives_a_fully_covered_customer():
    config, catalog, customers = _dataset()
    # simulate a customer whose contract covers every category: must not crash selection
    all_categories = sorted({sku["category"] for sku in catalog})
    customers[0]["contracts"][0]["covered_categories"] = all_categories
    cases = select_cases(config, catalog, customers)
    mismatch_cases = [c for c in cases if c["scenario_type"] == "discount_category_mismatch"]
    assert len(mismatch_cases) == 10


import json

from data_gen.scenario_gen import build_prompt_batches, write_prompt_batches


def _sample_cases():
    return [
        {
            "case_id": f"sc-{i:04d}",
            "scenario_type": "clean_distinct",
            "customer": {"name": "Metro Plumbing", "contact": "Ravi Patel"},
            "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        }
        for i in range(1, 26)
    ]


def test_batches_split_by_batch_size():
    batches = build_prompt_batches(_sample_cases(), batch_size=10)
    assert len(batches) == 3  # 25 cases -> 10 + 10 + 5


def test_each_batch_embeds_valid_json_for_its_cases():
    cases = _sample_cases()[:10]
    batches = build_prompt_batches(cases, batch_size=10)
    start = batches[0].index("Cases:\n") + len("Cases:\n")
    embedded = json.loads(batches[0][start:])
    assert len(embedded) == 10
    assert embedded[0]["case_id"] == "sc-0001"


def test_write_prompt_batches_numbers_files_sequentially(tmp_path):
    batches = build_prompt_batches(_sample_cases(), batch_size=10)
    paths = write_prompt_batches(batches, tmp_path)
    assert [p.name for p in paths] == ["batch_001.md", "batch_002.md", "batch_003.md"]
    for path in paths:
        assert path.exists()


def test_write_prompt_batches_continues_numbering_on_second_call(tmp_path):
    write_prompt_batches(build_prompt_batches(_sample_cases()[:5], batch_size=10), tmp_path)
    second = write_prompt_batches(build_prompt_batches(_sample_cases()[5:10], batch_size=10), tmp_path)
    assert second[0].name == "batch_002.md"


def test_write_prompt_batches_skips_gaps_in_numbering(tmp_path):
    # Pre-seed directory with batch_001.md and batch_003.md (gap at 002)
    (tmp_path / "batch_001.md").write_text("batch 1")
    (tmp_path / "batch_003.md").write_text("batch 3")
    # Writing new batches should start at 004.md (max existing + 1), not overwrite existing
    batches = build_prompt_batches(_sample_cases()[:5], batch_size=10)
    paths = write_prompt_batches(batches, tmp_path)
    assert paths[0].name == "batch_004.md"
    assert not (tmp_path / "batch_002.md").exists()
    assert (tmp_path / "batch_003.md").exists()  # Original file untouched


from data_gen.scenario_gen import ingest_responses, rebatch_rejected, write_scenarios


def _three_cases():
    return [
        {
            "case_id": "sc-0001", "scenario_type": "clean_distinct",
            "customer": {"name": "A", "contact": "B"}, "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        },
        {
            "case_id": "sc-0002", "scenario_type": "duplicate_pair",
            "customer": {"name": "A", "contact": "B"}, "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        },
        {
            "case_id": "sc-0003", "scenario_type": "clean_distinct",
            "customer": {"name": "A", "contact": "B"}, "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0002"]},
        },
    ]


def test_accepts_a_valid_response(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "need a couple of these for the job, thanks"},
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert len(accepted) == 3
    assert rejected == {}


def test_rejects_empty_email_text(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "   "},
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert "sc-0001" in rejected
    assert rejected["sc-0001"] == "empty email_text"


def test_rejects_label_leaking_email(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "need a couple of these, thanks"},
        {"case_id": "sc-0002", "email_text": "this is a duplicate pair of my last request"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert rejected.get("sc-0002") == "email_text leaks scenario_type label"


def test_one_malformed_batch_does_not_block_other_batches(tmp_path):
    (tmp_path / "batch_001.json").write_text("{not valid json")
    (tmp_path / "batch_002.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    accepted_ids = {c["case_id"] for c in accepted}
    assert accepted_ids == {"sc-0002", "sc-0003"}
    assert rejected.get("sc-0001") == "missing from any response file"


def test_missing_case_is_reported(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "need a couple of these, thanks"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert rejected["sc-0002"] == "missing from any response file"
    assert rejected["sc-0003"] == "missing from any response file"


def test_rebatch_rejected_writes_only_rejected_cases(tmp_path):
    cases = _three_cases()
    rejected = {"sc-0002": "missing from any response file"}
    paths = rebatch_rejected(cases, rejected, tmp_path / "prompts")
    content = paths[0].read_text()
    assert "sc-0002" in content
    assert "sc-0001" not in content


def test_write_scenarios_sorts_by_case_id(tmp_path):
    accepted = [
        {"case_id": "sc-0003", "email_text": "c"},
        {"case_id": "sc-0001", "email_text": "a"},
    ]
    out = tmp_path / "scenarios.json"
    write_scenarios(accepted, out)
    written = json.loads(out.read_text())
    assert [c["case_id"] for c in written] == ["sc-0001", "sc-0003"]


def test_write_scenarios_refuses_to_overwrite_without_force(tmp_path):
    out = tmp_path / "scenarios.json"
    write_scenarios([{"case_id": "sc-0001", "email_text": "a"}], out)
    try:
        write_scenarios([{"case_id": "sc-0002", "email_text": "b"}], out)
        assert False, "expected FileExistsError"
    except FileExistsError:
        pass


def test_wrong_shaped_response_json_does_not_crash_other_batches(tmp_path):
    # Top-level object (dict) instead of array in batch_001.json
    (tmp_path / "batch_001.json").write_text(json.dumps({
        "case_id": "sc-0001", "email_text": "need a couple of these, thanks"
    }))
    # Valid batch in batch_002.json
    (tmp_path / "batch_002.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    # Should not raise, should process batch_002 successfully
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    accepted_ids = {c["case_id"] for c in accepted}
    assert accepted_ids == {"sc-0002", "sc-0003"}
    # sc-0001 is missing (was in malformed batch_001)
    assert rejected.get("sc-0001") == "missing from any response file"


def test_rebatch_last_write_wins_when_earlier_rejection_is_later_accepted(tmp_path):
    # batch_001 rejects sc-0002 (duplicate_pair) as a label leak; batch_002, processed after it
    # in filename order (simulating a re-batch round), accepts the same case with a clean rewrite.
    # The later verdict must win: sc-0002 ends up accepted, not stuck in rejected forever.
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "this is a duplicate pair of my last request"},
    ]))
    (tmp_path / "batch_002.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    accepted_ids = {c["case_id"] for c in accepted}
    assert "sc-0002" in accepted_ids
    assert "sc-0002" not in rejected


def test_rebatch_last_write_wins_when_earlier_acceptance_is_later_rejected(tmp_path):
    # Reverse order: batch_001 accepts sc-0002; batch_002, processed after it, rejects the
    # same case. The later (rejecting) verdict must win.
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
    ]))
    (tmp_path / "batch_002.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "this is a duplicate pair of my last request"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    accepted_ids = {c["case_id"] for c in accepted}
    assert "sc-0002" not in accepted_ids
    assert rejected.get("sc-0002") == "email_text leaks scenario_type label"


def test_utf8_email_text_round_trips_without_mojibake(tmp_path):
    text = "Need the “deluxe” version, café spec please"
    (tmp_path / "batch_001.json").write_text(
        json.dumps([{"case_id": "sc-0001", "email_text": text}]), encoding="utf-8"
    )
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    matched = next(c for c in accepted if c["case_id"] == "sc-0001")
    assert matched["email_text"] == text


def test_non_string_email_text_is_rejected_not_crashed(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": None},
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)  # must not raise
    assert rejected.get("sc-0001") == "empty email_text"
    accepted_ids = {c["case_id"] for c in accepted}
    assert "sc-0001" not in accepted_ids


def test_revision_pair_word_repair_is_not_a_false_label_leak(tmp_path):
    cases = [{
        "case_id": "sc-0010", "scenario_type": "revision_pair",
        "customer": {"name": "A", "contact": "B"},
        "entities": {"customer_id": "CUST-0001", "site_id": "SITE-0001", "sku_ids": ["SKU-0001"],
                     "pair_id": "rev-0001", "pair_role": "original"},
    }]
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0010", "email_text": "need pricing for the boiler repair job, thanks"},
    ]))
    accepted, rejected = ingest_responses(cases, tmp_path)
    assert "sc-0010" not in rejected
    assert {c["case_id"] for c in accepted} == {"sc-0010"}


def test_duplicate_pair_explicit_leak_without_the_word_pair_is_caught(tmp_path):
    cases = [{
        "case_id": "sc-0011", "scenario_type": "duplicate_pair",
        "customer": {"name": "A", "contact": "B"},
        "entities": {"customer_id": "CUST-0001", "site_id": "SITE-0001", "sku_ids": ["SKU-0001"],
                     "pair_id": "dup-0001", "pair_role": "first"},
    }]
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0011", "email_text": "this is a duplicate of my request"},
    ]))
    accepted, rejected = ingest_responses(cases, tmp_path)
    assert rejected.get("sc-0011") == "email_text leaks scenario_type label"
    assert accepted == []
