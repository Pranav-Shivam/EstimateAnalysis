from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reference_data.models import Contract, Customer, Site, Sku


def upsert_sku(
    session: Session, *, sku_id: str, name: str, category: str, list_price: float,
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


def all_customers(session: Session) -> list[Customer]:
    return list(session.scalars(select(Customer)))


def all_skus(session: Session) -> list[Sku]:
    return list(session.scalars(select(Sku)))


def contracts_for_customer(session: Session, customer_id: str) -> list[Contract]:
    return list(session.scalars(select(Contract).where(Contract.customer_id == customer_id)))
