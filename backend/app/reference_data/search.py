from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.reference_data.models import Customer, Sku
from app.reference_data.repository import all_customers, all_skus, get_customer, get_sku

# Looser than intake's 90: callers here read the candidate list and judge, they do not auto-resolve.
CUSTOMER_MATCH_THRESHOLD = 80
SKU_SEARCH_CUTOFF = 60
SKU_SEARCH_LIMIT = 5
CUSTOMER_SEARCH_LIMIT = 3


def find_skus(session: Session, query: str) -> list[Sku]:
    exact = get_sku(session, query)
    if exact is not None:
        return [exact]
    names = {s.sku_id: s.name for s in all_skus(session)}
    hits = process.extract(
        query, names, scorer=fuzz.WRatio, processor=str.lower, limit=SKU_SEARCH_LIMIT, score_cutoff=SKU_SEARCH_CUTOFF,
    )
    return [get_sku(session, key) for _, _, key in hits]


def find_customers(session: Session, query: str) -> list[Customer]:
    exact = get_customer(session, query)
    if exact is not None:
        return [exact]
    names = {c.customer_id: c.name for c in all_customers(session)}
    hits = process.extract(
        query, names, scorer=fuzz.token_sort_ratio, processor=str.lower, limit=CUSTOMER_SEARCH_LIMIT,
        score_cutoff=CUSTOMER_MATCH_THRESHOLD,
    )
    return [get_customer(session, key) for _, _, key in hits]
