import hashlib
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.reference_data.models import (
    Contact, Contract, Customer, PriceHistory, ProductFamily, Project, Site, Sku, SkuRequirement,
)


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


def set_sku_list_price(session: Session, sku_id: str, list_price: float) -> None:
    sku = session.get(Sku, sku_id)
    if sku is None:
        raise ValueError(f"consolidation references unknown SKU {sku_id}")
    sku.list_price = list_price


def add_contract_coverage(session: Session, contract_id: str, category: str) -> None:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise ValueError(f"consolidation references unknown contract {contract_id}")
    if category not in contract.covered_categories:
        contract.covered_categories = [*contract.covered_categories, category]


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


def upsert_family(session: Session, *, family_id: str, name: str, category: str) -> None:
    row = session.get(ProductFamily, family_id)
    if row is None:
        row = ProductFamily(family_id=family_id)
        session.add(row)
    row.name = name
    row.category = category


def set_sku_family(session: Session, sku_id: str, family_id: str) -> None:
    sku = session.get(Sku, sku_id)
    if sku is None:
        raise ValueError(f"structure references unknown SKU {sku_id}")
    sku.family_id = family_id


def upsert_project(session: Session, *, project_id: str, customer_id: str, site_id: str, name: str) -> None:
    row = session.get(Project, project_id)
    if row is None:
        row = Project(project_id=project_id)
        session.add(row)
    row.customer_id = customer_id
    row.site_id = site_id
    row.name = name


def upsert_contact(
    session: Session, *, contact_id: str, customer_id: str, name: str, email: str, phone: str,
) -> None:
    row = session.get(Contact, contact_id)
    if row is None:
        row = Contact(contact_id=contact_id)
        session.add(row)
    row.customer_id = customer_id
    row.name = name
    row.email = email
    row.phone = phone


def all_contracts(session: Session) -> list[Contract]:
    return list(session.scalars(select(Contract).order_by(Contract.contract_id)))


def all_sites(session: Session) -> list[Site]:
    return list(session.scalars(select(Site).order_by(Site.site_id)))


def all_requirements(session: Session) -> list[SkuRequirement]:
    return list(session.scalars(select(SkuRequirement).order_by(SkuRequirement.sku_id, SkuRequirement.required_sku_id)))


def all_families(session: Session) -> list[ProductFamily]:
    return list(session.scalars(select(ProductFamily).order_by(ProductFamily.family_id)))


def all_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.project_id)))


def all_contacts(session: Session) -> list[Contact]:
    return list(session.scalars(select(Contact).order_by(Contact.contact_id)))


def sites_for_customer(session: Session, customer_id: str) -> list[Site]:
    return list(session.scalars(select(Site).where(Site.customer_id == customer_id).order_by(Site.site_id)))


def project_for_site(session: Session, site_id: str) -> Project | None:
    return session.scalar(select(Project).where(Project.site_id == site_id))


def reference_fingerprint(session: Session) -> str:
    """Digest of the reference rows the graph guardrail depends on. The graph stores it at rebuild time; a
    mismatch later means Postgres moved on and the graph is stale."""
    digest = hashlib.md5(usedforsecurity=False)
    statements = (
        select(Sku.sku_id, Sku.category, Sku.discontinued, Sku.replaced_by, Sku.family_id, Sku.in_stock)
        .order_by(Sku.sku_id),
        select(SkuRequirement.sku_id, SkuRequirement.required_sku_id)
        .order_by(SkuRequirement.sku_id, SkuRequirement.required_sku_id),
        select(
            Contract.contract_id, Contract.customer_id, Contract.covered_categories, Contract.effective_from,
            Contract.effective_to, Contract.discount_pct,
        ).order_by(Contract.contract_id),
    )
    for statement in statements:
        for row in session.execute(statement):
            digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"|")
    return digest.hexdigest()


def skus_by_ids(session: Session, sku_ids: set[str]) -> list[Sku]:
    if not sku_ids:
        return []
    return list(session.scalars(select(Sku).where(Sku.sku_id.in_(sku_ids))))
