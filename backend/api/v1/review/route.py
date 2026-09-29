from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.v1.review.response import ReviewItemListResponse
from app.judge.repository import list_open_review_items
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
