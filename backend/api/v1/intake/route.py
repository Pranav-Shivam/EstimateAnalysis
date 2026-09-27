from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.intake.request import IntakeRequest
from api.v1.intake.response import IntakeResponse, LineItemResponse
from app.intake.service import process_email
from core.config.settings import Settings
from core.db.session import get_session
from core.llm.openai_client import ExtractionError, OpenAIExtractionClient

router = APIRouter(prefix="/v1/intake", tags=["intake"])


def get_llm_client() -> OpenAIExtractionClient:
    from openai import OpenAI

    settings = Settings()
    return OpenAIExtractionClient(client=OpenAI(api_key=settings.openai_api_key))


@router.post("", response_model=IntakeResponse)
def submit_email(
    body: IntakeRequest,
    session: Session = Depends(get_session),
    llm_client: OpenAIExtractionClient = Depends(get_llm_client),
) -> IntakeResponse:
    try:
        result = process_email(session, body.email_text, llm_client)
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail="failed to extract quote request from email") from exc

    session.commit()

    return IntakeResponse(
        quote_request_id=result.row.id,
        customer_id=result.row.customer_id,
        site_id=result.row.site_id,
        contract_id=result.row.contract_id,
        line_items=[
            LineItemResponse(sku_name_as_written=li.sku_name_as_written, sku_id=li.sku_id, quantity=li.quantity)
            for li in result.resolved_line_items
        ],
    )
