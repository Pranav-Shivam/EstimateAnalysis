import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.review.request import ResolveReviewItemRequest
from api.v1.review.response import ResolveReviewItemResponse, ReviewItemListResponse
from app.judge.repository import list_open_review_items
from app.judge.schemas import InvalidCorrection
from app.judge.service import (
    ReviewItemAlreadyResolved, ReviewItemNotFound, ReviewItemNotResolvable, resolve_review_item,
)
from core.db.session import get_session

router = APIRouter(prefix="/v1/review", tags=["review"])


@router.get("", response_model=list[ReviewItemListResponse])
def list_review_items(session: Session = Depends(get_session)) -> list[ReviewItemListResponse]:
    return [
        ReviewItemListResponse(
            id=item.id, estimate_id=item.estimate_id, dimension=item.dimension, fact=item.fact,
            evidence=item.evidence, line_index=item.line_index, status=item.status, created_at=item.created_at,
        )
        for item in list_open_review_items(session)
    ]


@router.post("/{review_item_id}/resolve", response_model=ResolveReviewItemResponse)
def resolve(
    review_item_id: uuid.UUID, body: ResolveReviewItemRequest, session: Session = Depends(get_session),
) -> ResolveReviewItemResponse:
    try:
        result = resolve_review_item(session, review_item_id, body.outcome, body.correction)
    except ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewItemAlreadyResolved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewItemNotResolvable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCorrection as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.commit()
    return ResolveReviewItemResponse(
        id=result.row.id, status=result.row.status, outcome=result.row.outcome, correction=result.row.correction,
        consolidation_enqueued=result.consolidation_enqueued,
    )
