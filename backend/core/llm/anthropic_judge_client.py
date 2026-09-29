import json
from dataclasses import dataclass

import anthropic

DIMENSION_NAMES = ("contract_discount", "graph_completion", "price_provenance")
JUDGE_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

SCORE_TOOL = {
    "name": "submit_scores",
    "description": "Submit one score (0 to 1) and a one-sentence rationale for each of the three dimensions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": list(DIMENSION_NAMES)},
                        "score": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "score", "rationale"],
                },
            },
        },
        "required": ["dimensions"],
    },
}


class JudgeError(Exception):
    pass


@dataclass(frozen=True)
class RawDimensionScore:
    name: str
    score: float
    rationale: str


@dataclass(frozen=True)
class RawJudgeScore:
    dimensions: list[RawDimensionScore]


class AnthropicJudgeClient:
    def __init__(self, client: "anthropic.Anthropic | None" = None) -> None:
        self._client = client or anthropic.Anthropic()

    def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore:
        try:
            response = self._client.messages.create(
                model=JUDGE_MODEL, max_tokens=MAX_TOKENS, system=system_prompt,
                messages=[{"role": "user", "content": json.dumps({"lines": evidence})}],
                tools=[SCORE_TOOL], tool_choice={"type": "tool", "name": "submit_scores"},
            )
        except Exception as exc:
            raise JudgeError(f"Anthropic judge call failed: {exc}") from exc

        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            raise JudgeError("Anthropic returned no tool_use block")
        return _parse_scores(block.input)


def _parse_scores(payload: dict) -> RawJudgeScore:
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, list) or len(raw_dimensions) != len(DIMENSION_NAMES):
        raise JudgeError(f"expected {len(DIMENSION_NAMES)} dimensions, got {raw_dimensions!r}")

    dimensions = []
    seen = set()
    for entry in raw_dimensions:
        name = entry.get("name")
        score = entry.get("score")
        rationale = entry.get("rationale")
        if name not in DIMENSION_NAMES:
            raise JudgeError(f"unknown dimension name {name!r}")
        if name in seen:
            raise JudgeError(f"dimension {name!r} was scored more than once")
        seen.add(name)
        if not isinstance(score, (int, float)) or not (0.0 <= score <= 1.0):
            raise JudgeError(f"dimension {name!r} score {score!r} is not a number in [0, 1]")
        if not isinstance(rationale, str) or not rationale.strip():
            raise JudgeError(f"dimension {name!r} has no rationale")
        dimensions.append(RawDimensionScore(name=name, score=float(score), rationale=rationale.strip()))
    return RawJudgeScore(dimensions=dimensions)
