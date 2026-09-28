from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.reference_data.models import Contract, Customer, PriceHistory, Site, Sku, SkuRequirement


def upsert_sku(
    session: Session, *, sku_id: str, name: str, category: str, list_price: float | None,
    discontinued: bool, replaced_by: str | None, in_stock: bool,
) -> None:
    row = session.get(Sku, sku_id)
    if row is None:
        row = Sku(sku_id=sku_id)
        session.add(row)
    row.name = name
    row.category = category
    row.list_price = list_price
    row.discontinued = discontinued
    row.replaced_by = replaced_by
    row.in_stock = in_stock


def upsert_customer(session: Session, *, customer_id: str, name: str, account_tier: str) -> None:
    row = session.get(Customer, customer_id)
    if row is None:
        row = Customer(customer_id=customer_id)
        session.add(row)
    row.name = name
    row.account_tier = account_tier


def upsert_site(session: Session, *, site_id: str, customer_id: str, address: str, zip_code: str) -> None:
    row = session.get(Site, site_id)
    if row is None:
        row = Site(site_id=site_id)
        session.add(row)
    row.customer_id = customer_id
    row.address = address
    row.zip = zip_code


def upsert_contract(
    session: Session, *, contract_id: str, customer_id: str, discount_category: str,
    covered_categories: list[str], effective_from: date, effective_to: date,
    discount_pct: float = 0.0,
) -> None:
    row = session.get(Contract, contract_id)
    if row is None:
        row = Contract(contract_id=contract_id)
        session.add(row)
    row.customer_id = customer_id
    row.discount_category = discount_category
    row.covered_categories = covered_categories
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.discount_pct = discount_pct


def all_customers(session: Session) -> list[Customer]:
    return list(session.scalars(select(Customer).order_by(Customer.customer_id)))


def all_skus(session: Session) -> list[Sku]:
    return list(session.scalars(select(Sku).order_by(Sku.sku_id)))


def contracts_for_customer(session: Session, customer_id: str) -> list[Contract]:
    return list(session.scalars(select(Contract).where(Contract.customer_id == customer_id)))


def get_sku(session: Session, sku_id: str) -> Sku | None:
    return session.get(Sku, sku_id)


def get_customer(session: Session, customer_id: str) -> Customer | None:
    return session.get(Customer, customer_id)


def get_contract(session: Session, contract_id: str) -> Contract | None:
    return session.get(Contract, contract_id)


def upsert_requirement(session: Session, *, sku_id: str, required_sku_id: str) -> None:
    # Sessions here run with autoflush off: flush first so merge sees a row added by an earlier call and does not duplicate it.
    session.flush()
    session.merge(SkuRequirement(sku_id=sku_id, required_sku_id=required_sku_id))


def required_sku_ids(session: Session, sku_id: str) -> list[str]:
    return list(session.scalars(
        select(SkuRequirement.required_sku_id).where(SkuRequirement.sku_id == sku_id).order_by(SkuRequirement.required_sku_id)
    ))


def replace_price_history(session: Session, sku_id: str, rows: list[tuple[float, date]]) -> None:
    # Sessions here run with autoflush off: flush first so rows added by an earlier call are deleted too.
    session.flush()
    session.execute(delete(PriceHistory).where(PriceHistory.sku_id == sku_id))
    for unit_price, quoted_on in rows:
        session.add(PriceHistory(sku_id=sku_id, unit_price=unit_price, quoted_on=quoted_on))


def latest_realized_price(session: Session, sku_id: str) -> float | None:
    return session.scalar(
        select(PriceHistory.unit_price).where(PriceHistory.sku_id == sku_id)
        .order_by(PriceHistory.quoted_on.desc(), PriceHistory.id.desc()).limit(1)
    )


def skus_with_list_price_in_category(session: Session, category: str) -> list[Sku]:
    return list(session.scalars(
        select(Sku).where(Sku.category == category, Sku.list_price.is_not(None)).order_by(Sku.sku_id)
    ))
