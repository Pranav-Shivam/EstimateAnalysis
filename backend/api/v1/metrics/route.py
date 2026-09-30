from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.v1.metrics.response import MetricsResponse
from app.metrics.service import compute_metrics
from core.db.session import get_session

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(session: Session = Depends(get_session)) -> MetricsResponse:
    return MetricsResponse.model_validate(compute_metrics(session), from_attributes=True)
