import statistics
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.reference_data.models import Sku
from app.reference_data.repository import skus_with_list_price_in_category

PEER_MIN = 3


@dataclass(frozen=True)
class Prediction:
    price: float
    low: float
    high: float
    peer_count: int


def predict_price_for_sku(session: Session, sku: Sku) -> Prediction | None:
    peer_prices = [peer.list_price for peer in skus_with_list_price_in_category(session, sku.category)]
    if len(peer_prices) < PEER_MIN:
        return None
    low, _, high = statistics.quantiles(peer_prices, n=4, method="inclusive")
    return Prediction(
        price=round(statistics.median(peer_prices), 2), low=round(low, 2), high=round(high, 2),
        peer_count=len(peer_prices),
    )
