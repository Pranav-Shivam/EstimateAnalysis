from app.intake.resolution import resolve_extraction
from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.reference_data.repository import upsert_customer, upsert_sku


def _seed(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Bramblewick Contractors", account_tier="Standard")
    upsert_customer(db_session, customer_id="CUST-B", name="Bramblewick Plumbing", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Quazzlebolt Sprayer Assembly", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()


def test_exact_match_resolves_customer_and_sku(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Bramblewick Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Quazzlebolt Sprayer Assembly", quantity="4")],
        raw_text="text",
    )
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id == "CUST-A"
    assert result.line_items[0].sku_id == "SKU-A"


def test_fuzzy_match_resolves_shorthand_name(db_session):
    upsert_customer(db_session, customer_id="CUST-C", name="Quazzlebolt Industrial Group", account_tier="Standard")
    db_session.flush()
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Quazzlebolt Industrial Grp",
        line_items=[],
        raw_text="text",
    )
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id == "CUST-C"


def test_ambiguous_name_tie_resolves_to_none(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written="Bramblewick", line_items=[], raw_text="text")
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id is None


def test_unresolvable_sku_name_stays_unresolved_without_blocking_others(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Bramblewick Contractors",
        line_items=[
            LineItemExtraction(sku_name_as_written="Quazzlebolt Sprayer Assembly", quantity="1"),
            LineItemExtraction(sku_name_as_written="Some Totally Unknown Part", quantity="1"),
        ],
        raw_text="text",
    )
    result = resolve_extraction(db_session, extraction)
    assert result.line_items[0].sku_id == "SKU-A"
    assert result.line_items[1].sku_id is None


def test_empty_line_items_resolves_to_empty_list(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written="Bramblewick Contractors", line_items=[], raw_text="text")
    result = resolve_extraction(db_session, extraction)
    assert result.line_items == []


def test_missing_customer_name_resolves_to_none_without_crashing(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written=None, line_items=[], raw_text="-Anil")
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id is None
