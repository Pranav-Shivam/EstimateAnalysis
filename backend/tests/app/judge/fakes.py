from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore


def full_line_evidence(sku_id: str, line_index: int = 0) -> dict:
    """One line's complete judge evidence (all three dimensions and the unit price), the shape run_judge stores
    under a review item's evidence["line_evidence"] and the golden set uses. A predicted-price line."""
    return {
        "line_index": line_index, "sku_id": sku_id, "unit_price": 20.0,
        "price": {"price_source": "predicted", "list_price": None, "predicted_price": 20.0, "peer_count": 3,
                  "low": 10.0, "high": 30.0},
        "contract": {"discount_pct": 0.0, "contract_id": None, "covered": None, "active_on_as_of": None,
                     "days_to_expiry": None},
        "graph": {"discontinued": False, "live_sku_id": sku_id, "required_part_ids": [],
                  "missing_required_part_ids": []},
    }


class ScriptedJudgeClient:
    """Returns the same scripted dimensions on every call. Records how many times it was called so a test
    can assert the fast path made zero calls."""

    def __init__(self, dimensions: list[dict]) -> None:
        self._dimensions = dimensions
        self.calls = 0

    def score(self, evidence, system_prompt) -> RawJudgeScore:
        self.calls += 1
        return RawJudgeScore(dimensions=[RawDimensionScore(**d) for d in self._dimensions])
