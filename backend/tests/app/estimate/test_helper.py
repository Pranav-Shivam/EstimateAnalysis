from app.estimate.helper import compute_totals
from app.estimate.schemas import DraftLine


def _line(quantity, unit_price, discount_pct=0.0):
    return DraftLine(sku_id="SKU-X", quantity=quantity, unit_price=unit_price, price_source="list",
                     discount_pct=discount_pct)


def test_totals_apply_discount_per_line():
    totals = compute_totals([_line(3, 100.0, 10.0), _line(2, 50.0)])

    assert totals.list_total == 400.0
    assert totals.discount_total == 30.0
    assert totals.net_total == 370.0


def test_totals_skip_incomplete_lines():
    incomplete = DraftLine(sku_id="SKU-X", quantity=None, unit_price=10.0, price_source="list")

    totals = compute_totals([incomplete, _line(1, 10.0)])

    assert totals.list_total == 10.0
    assert totals.net_total == 10.0


def test_totals_of_no_lines_are_zero():
    totals = compute_totals([])

    assert (totals.list_total, totals.discount_total, totals.net_total) == (0.0, 0.0, 0.0)
