from datetime import date

from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config
from data_gen.customer_gen import generate_customers


def _config(customer_count=125):
    return Config(seed=42, sku_count=650, customer_count=customer_count, scenarios_per_type=10)


def _catalog():
    return generate_catalog(_config())


def test_generates_requested_count():
    customers = generate_customers(_config(), _catalog())
    assert len(customers) == 125


def test_every_customer_has_contact_site_and_contract():
    for customer in generate_customers(_config(), _catalog()):
        assert len(customer["contacts"]) >= 1
        assert len(customer["sites"]) >= 1
        assert len(customer["contracts"]) >= 1


def test_contract_effective_from_precedes_effective_to():
    for customer in generate_customers(_config(), _catalog()):
        for contract in customer["contracts"]:
            start = date.fromisoformat(contract["effective_from"])
            end = date.fromisoformat(contract["effective_to"])
            assert start < end


def test_deterministic_across_two_runs():
    catalog = _catalog()
    first = generate_customers(_config(), catalog)
    second = generate_customers(_config(), catalog)
    assert first == second


def test_rejects_customer_count_larger_than_available_combinations():
    huge = _config(customer_count=1_000_000)
    try:
        generate_customers(huge, _catalog())
        assert False, "expected ValueError for an unreachable customer_count"
    except ValueError:
        pass


def test_supports_maximum_documented_customer_count():
    """Verify customer_count can reach the documented ceiling of 150."""
    customers = generate_customers(_config(customer_count=150), _catalog())
    assert len(customers) == 150
