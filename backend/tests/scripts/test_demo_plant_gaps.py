import pytest

from demo.fakes import DemoSetupError
from demo.scenarios import DemoCase
from demo.seed import plant_gaps
from tests.app.estimate.seed import seed_world

SCENARIO = {"case_id": "sc-x"}


def test_plants_a_price_gap_once(db_session):
    seed_world(db_session)

    plant_gaps(db_session, [DemoCase("price_gap", SCENARIO, "flagged:price_provenance", price_gap="SKU-E-A1")])

    with pytest.raises(DemoSetupError):
        plant_gaps(db_session, [DemoCase("price_gap", SCENARIO, "flagged:price_provenance", price_gap="SKU-E-A1")])


def test_refuses_a_price_gap_on_a_sku_that_is_already_unpriced(db_session):
    seed_world(db_session)

    with pytest.raises(DemoSetupError):
        plant_gaps(db_session, [DemoCase("price_gap", SCENARIO, "flagged:price_provenance", price_gap="SKU-E-GAP")])


def test_refuses_a_graph_gap_whose_requirement_is_already_gone(db_session):
    seed_world(db_session)
    case = DemoCase("graph_gap", SCENARIO, "flagged:graph_completion", graph_gap=("SKU-E-B1", "SKU-E-A1"))

    plant_gaps(db_session, [case])

    with pytest.raises(DemoSetupError):
        plant_gaps(db_session, [case])
