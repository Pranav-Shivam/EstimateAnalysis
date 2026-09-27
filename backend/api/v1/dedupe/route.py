import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.dedupe.response import DedupeResponse, DedupeVerdictResponse
from app.dedupe.service import run_dedupe
from core.db.session import get_session

router = APIRouter(prefix="/v1/dedupe", tags=["dedupe"])


@router.post("/{quote_request_id}", response_model=DedupeResponse)
def dedupe_quote_request(quote_request_id: uuid.UUID, session: Session = Depends(get_session)) -> DedupeResponse:
    try:
        verdicts = run_dedupe(session, quote_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session.commit()

    return DedupeResponse(
        quote_request_id=quote_request_id,
        verdicts=[
            DedupeVerdictResponse(
                candidate_quote_request_id=v.candidate_quote_request_id, verdict=v.verdict,
                content_jaccard=v.content_jaccard, style_jaccard=v.style_jaccard, signals_fired=v.signals_fired,
            )
            for v in verdicts
        ],
    )
