from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.intake.schemas import QuoteRequestExtraction
from app.reference_data.repository import all_customers, all_skus

FUZZY_MATCH_THRESHOLD = 90


@dataclass
class ResolvedLineItem:
    sku_name_as_written: str
    sku_id: str | None
    quantity: str | None


@dataclass
class IntakeResult:
    customer_id: str | None
    site_id: str | None
    line_items: list[ResolvedLineItem]
    extraction: QuoteRequestExtraction


def _match_name(name: str, candidates: dict[str, str]) -> str | None:
    lowered = name.strip().lower()
    exact = [cid for cid, cname in candidates.items() if cname.strip().lower() == lowered]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    scored = [(cid, fuzz.token_sort_ratio(lowered, cname.strip().lower())) for cid, cname in candidates.items()]
    above_threshold = [cid for cid, score in scored if score >= FUZZY_MATCH_THRESHOLD]
    if len(above_threshold) == 1:
        return above_threshold[0]
    return None


def resolve_extraction(session: Session, extraction: QuoteRequestExtraction) -> IntakeResult:
    customer_candidates = {c.customer_id: c.name for c in all_customers(session)}
    sku_candidates = {s.sku_id: s.name for s in all_skus(session)}

    customer_id = (
        _match_name(extraction.customer_name_as_written, customer_candidates)
        if extraction.customer_name_as_written
        else None
    )
    line_items = [
        ResolvedLineItem(
            sku_name_as_written=item.sku_name_as_written,
            sku_id=_match_name(item.sku_name_as_written, sku_candidates),
            quantity=item.quantity,
        )
        for item in extraction.line_items
    ]
    return IntakeResult(customer_id=customer_id, site_id=None, line_items=line_items, extraction=extraction)
