import uuid

from sqlalchemy.orm import Session

from app.intake.models import QuoteRequestRow


def save_quote_request(
    session: Session, *, raw_email_text: str, parsed_json: dict, content_fingerprint: dict,
    style_fingerprint: dict, customer_id: str | None, site_id: str | None = None,
    contract_id: str | None = None, case_id: str | None = None,
) -> QuoteRequestRow:
    row = QuoteRequestRow(
        id=uuid.uuid4(), case_id=case_id, customer_id=customer_id, site_id=site_id,
        contract_id=contract_id, raw_email_text=raw_email_text, parsed_json=parsed_json,
        content_fingerprint=content_fingerprint, style_fingerprint=style_fingerprint,
    )
    session.add(row)
    session.flush()
    return row


def get_quote_request(session: Session, quote_request_id: uuid.UUID) -> QuoteRequestRow | None:
    return session.get(QuoteRequestRow, quote_request_id)
