import pytest
from pydantic import ValidationError

from app.estimate.constant import MAX_LINE_QUANTITY
from app.estimate.schemas import DraftLine


def test_quantity_at_the_cap_is_accepted():
    assert DraftLine(quantity=MAX_LINE_QUANTITY).quantity == 100_000


def test_quantity_above_the_cap_is_rejected():
    with pytest.raises(ValidationError):
        DraftLine(quantity=MAX_LINE_QUANTITY + 1)


def test_zero_and_negative_quantity_still_parse_so_the_guardrail_can_report_them_per_line():
    assert DraftLine(quantity=0).quantity == 0
    assert DraftLine(quantity=-2).quantity == -2
