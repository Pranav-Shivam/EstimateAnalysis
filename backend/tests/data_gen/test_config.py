import pytest

from data_gen.config import Config, DEFAULT, validate_config


def test_default_config_is_valid():
    validate_config(DEFAULT)


def test_rejects_zero_sku_count():
    bad = Config(seed=1, sku_count=0, customer_count=100, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_negative_customer_count():
    bad = Config(seed=1, sku_count=500, customer_count=-5, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_zero_scenarios_per_type():
    bad = Config(seed=1, sku_count=500, customer_count=100, scenarios_per_type=0)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_missing_seed():
    bad = Config(seed=None, sku_count=500, customer_count=100, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_sku_count_below_documented_range():
    bad = Config(seed=1, sku_count=499, customer_count=100, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_sku_count_above_documented_range():
    bad = Config(seed=1, sku_count=801, customer_count=100, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_accepts_sku_count_at_documented_range_boundaries():
    validate_config(Config(seed=1, sku_count=500, customer_count=100, scenarios_per_type=10))
    validate_config(Config(seed=1, sku_count=800, customer_count=100, scenarios_per_type=10))


def test_rejects_customer_count_below_documented_range():
    bad = Config(seed=1, sku_count=500, customer_count=99, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_customer_count_above_documented_range():
    bad = Config(seed=1, sku_count=500, customer_count=151, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_accepts_customer_count_at_documented_range_boundaries():
    validate_config(Config(seed=1, sku_count=500, customer_count=100, scenarios_per_type=10))
    validate_config(Config(seed=1, sku_count=500, customer_count=150, scenarios_per_type=10))


def test_rejects_scenarios_per_type_not_equal_to_ten():
    bad = Config(seed=1, sku_count=500, customer_count=100, scenarios_per_type=11)
    with pytest.raises(ValueError):
        validate_config(bad)
