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
