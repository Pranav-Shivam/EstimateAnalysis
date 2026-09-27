import uuid

from sqlalchemy.orm import Session

from app.dedupe.fingerprints import classify, jaccard
from app.dedupe.models import DedupeVerdictRow
from app.dedupe.repository import find_blocked_candidates, save_verdict
from app.intake.models import QuoteRequestRow


def _blocking_signals(target: QuoteRequestRow, candidate: QuoteRequestRow) -> list[str]:
    signals = []
    if target.customer_id and target.customer_id == candidate.customer_id:
        signals.append("same_customer")
    if target.site_id and target.site_id == candidate.site_id:
        signals.append("same_site")
    if target.contract_id and target.contract_id == candidate.contract_id:
        signals.append("same_contract")
    return signals


def run_dedupe(session: Session, quote_request_id: uuid.UUID) -> list[DedupeVerdictRow]:
    target = session.get(QuoteRequestRow, quote_request_id)
    if target is None:
        raise ValueError(f"quote_request {quote_request_id} not found")

    candidates = find_blocked_candidates(session, target)
    verdicts: list[DedupeVerdictRow] = []

    target_sku_ids = set(target.content_fingerprint.get("sku_ids", []))
    target_tokens = set(target.style_fingerprint.get("tokens", []))

    for candidate in candidates:
        candidate_sku_ids = set(candidate.content_fingerprint.get("sku_ids", []))
        candidate_tokens = set(candidate.style_fingerprint.get("tokens", []))

        verdict, content_score, content_signals = classify(target_sku_ids, candidate_sku_ids)
        style_score = jaccard(target_tokens, candidate_tokens)
        signals = _blocking_signals(target, candidate) + content_signals

        row = save_verdict(
            session, quote_request_id=target.id, candidate_quote_request_id=candidate.id,
            verdict=verdict, content_jaccard=content_score, style_jaccard=style_score, signals_fired=signals,
        )
        verdicts.append(row)

    return verdicts
