from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.dedupe.fingerprints import normalize_style_tokens
from app.intake.models import QuoteRequestRow
from app.intake.repository import save_quote_request
from app.intake.resolution import ResolvedLineItem, resolve_extraction
from app.reference_data.repository import contracts_for_customer
from core.llm.openai_client import OpenAIExtractionClient


@dataclass
class ProcessEmailResult:
    row: QuoteRequestRow
    resolved_line_items: list[ResolvedLineItem]


def process_email(
    session: Session, email_text: str, llm_client: OpenAIExtractionClient, case_id: str | None = None,
) -> ProcessEmailResult:
    extraction = llm_client.extract_quote_request(email_text)
    resolved = resolve_extraction(session, extraction)

    resolved_sku_ids = [item.sku_id for item in resolved.line_items if item.sku_id]
    content_fingerprint = {"sku_ids": sorted(set(resolved_sku_ids))}
    style_fingerprint = {"tokens": sorted(normalize_style_tokens(email_text))}

    contract_id = None
    if resolved.customer_id:
        contracts = contracts_for_customer(session, resolved.customer_id)
        if len(contracts) == 1:
            contract_id = contracts[0].contract_id

    row = save_quote_request(
        session, raw_email_text=email_text, parsed_json=extraction.model_dump(),
        content_fingerprint=content_fingerprint, style_fingerprint=style_fingerprint,
        customer_id=resolved.customer_id, site_id=resolved.site_id, contract_id=contract_id, case_id=case_id,
    )
    return ProcessEmailResult(row=row, resolved_line_items=resolved.line_items)
