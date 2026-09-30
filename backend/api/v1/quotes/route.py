import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.quotes.response import QuoteDetailResponse, QuoteSummaryResponse
from app.quotes.service import QuoteNotFound, get_quote_detail, list_quotes
from core.db.session import get_session

router = APIRouter(prefix="/v1/quotes", tags=["quotes"])


@router.get("", response_model=list[QuoteSummaryResponse])
def list_all_quotes(session: Session = Depends(get_session)) -> list[QuoteSummaryResponse]:
    return [QuoteSummaryResponse.model_validate(summary, from_attributes=True) for summary in list_quotes(session)]


@router.get("/{quote_request_id}", response_model=QuoteDetailResponse)
def get_quote(quote_request_id: uuid.UUID, session: Session = Depends(get_session)) -> QuoteDetailResponse:
    try:
        detail = get_quote_detail(session, quote_request_id)
    except QuoteNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return QuoteDetailResponse.model_validate(detail, from_attributes=True)
