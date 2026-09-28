from datetime import date

from app.reference_data.repository import (
    replace_price_history, set_sku_family, upsert_contact, upsert_contract, upsert_customer, upsert_family,
    upsert_project, upsert_requirement, upsert_site, upsert_sku,
)

AS_OF = date(2024, 9, 1)


def _sku(session, sku_id, name, category, list_price, *, discontinued=False, replaced_by=None, in_stock=True):
    upsert_sku(
        session, sku_id=sku_id, name=name, category=category, list_price=list_price,
        discontinued=discontinued, replaced_by=replaced_by, in_stock=in_stock,
    )


def seed_world(session) -> None:
    """Customer CUST-E1 has contract CTR-E1 (10% on Cat-E-A only, active on AS_OF). CUST-E2 has no contract.

    SKU-E-A1 (Cat-E-A, 100) and SKU-E-B1 (Cat-E-B, 50, requires SKU-E-A1). SKU-E-OLD is discontinued and
    replaced by SKU-E-A1, out of stock. Cat-E-P has three priced peers (10, 20, 30) and a gap SKU-E-GAP.
    SKU-E-LONE is a gap SKU alone in its category.
    """
    upsert_customer(session, customer_id="CUST-E1", name="Vexthorn Mechanical", account_tier="Standard")
    upsert_customer(session, customer_id="CUST-E2", name="Nocontract Supply", account_tier="Standard")
    session.flush()
    upsert_contract(
        session, contract_id="CTR-E1", customer_id="CUST-E1", discount_category="Cat-E-A",
        covered_categories=["Cat-E-A"], effective_from=date(2024, 1, 1), effective_to=date(2025, 12, 31),
        discount_pct=10.0,
    )

    _sku(session, "SKU-E-A1", "Zorpwidget Alpha 9000", "Cat-E-A", 100.0)
    _sku(session, "SKU-E-B1", "Blorptek Bravo 100", "Cat-E-B", 50.0)
    _sku(session, "SKU-E-P1", "Peer One", "Cat-E-P", 10.0)
    _sku(session, "SKU-E-P2", "Peer Two", "Cat-E-P", 20.0)
    _sku(session, "SKU-E-P3", "Peer Three", "Cat-E-P", 30.0)
    _sku(session, "SKU-E-GAP", "Gapgizmo Prime", "Cat-E-P", None)
    _sku(session, "SKU-E-LONE", "Lonely Widget", "Cat-E-L", None)
    session.flush()
    _sku(session, "SKU-E-OLD", "Zorpwidget Alpha 8000", "Cat-E-A", 80.0,
         discontinued=True, replaced_by="SKU-E-A1", in_stock=False)
    session.flush()

    upsert_requirement(session, sku_id="SKU-E-B1", required_sku_id="SKU-E-A1")
    replace_price_history(session, "SKU-E-A1", [(95.0, date(2024, 3, 1)), (97.0, date(2024, 6, 1))])
    session.flush()


def seed_structure(session) -> None:
    """Adds the article's identity layer to seed_world: two sites for CUST-E1 (12 Elm Street in two cities, so a
    street-only hint is ambiguous), one project per site, a family holding SKU-E-A1 and SKU-E-OLD, one contact."""
    upsert_site(session, site_id="SITE-E1", customer_id="CUST-E1", address="12 Elm Street, Springfield, IL", zip_code="62701")
    upsert_site(session, site_id="SITE-E2", customer_id="CUST-E1", address="12 Elm Street, Portland, OR", zip_code="97201")
    upsert_family(session, family_id="FAM-E-A", name="Zorpwidget Alpha", category="Cat-E-A")
    session.flush()
    set_sku_family(session, "SKU-E-A1", "FAM-E-A")
    set_sku_family(session, "SKU-E-OLD", "FAM-E-A")
    upsert_project(session, project_id="PRJ-E1", customer_id="CUST-E1", site_id="SITE-E1", name="Vexthorn job at 12 Elm Street, Springfield")
    upsert_project(session, project_id="PRJ-E2", customer_id="CUST-E1", site_id="SITE-E2", name="Vexthorn job at 12 Elm Street, Portland")
    upsert_contact(
        session, contact_id="CUST-E1-C1", customer_id="CUST-E1", name="Ravi Kumar",
        email="ravi@vexthorn.example.com", phone="555-0100",
    )
    session.flush()
