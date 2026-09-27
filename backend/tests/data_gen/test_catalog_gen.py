from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config


def _config(sku_count=650):
    return Config(seed=42, sku_count=sku_count, customer_count=125, scenarios_per_type=10)


def test_generates_requested_count():
    catalog = generate_catalog(_config())
    assert len(catalog) == 650


def test_every_replaced_by_target_exists_and_is_not_discontinued():
    catalog = generate_catalog(_config())
    by_id = {s["sku_id"]: s for s in catalog}
    discontinued_with_replacement = [s for s in catalog if s["discontinued"]]
    assert discontinued_with_replacement, "expected at least one discontinued SKU"
    for sku in discontinued_with_replacement:
        assert sku["replaced_by"] in by_id
        assert by_id[sku["replaced_by"]]["discontinued"] is False


def test_every_requires_target_exists():
    catalog = generate_catalog(_config())
    by_id = {s["sku_id"]: s for s in catalog}
    skus_with_requires = [s for s in catalog if s["requires"]]
    assert skus_with_requires, "expected at least one SKU with a requires link"
    for sku in skus_with_requires:
        for target in sku["requires"]:
            assert target in by_id


def test_deterministic_across_two_runs():
    first = generate_catalog(_config())
    second = generate_catalog(_config())
    assert first == second


def test_rejects_sku_count_larger_than_available_combinations():
    huge = _config(sku_count=1_000_000)
    try:
        generate_catalog(huge)
        assert False, "expected ValueError for an unreachable sku_count"
    except ValueError:
        pass


def test_supports_maximum_documented_sku_count():
    catalog = generate_catalog(_config(sku_count=800))
    assert len(catalog) == 800
