from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore


class ScriptedJudgeClient:
    """Returns the same scripted dimensions on every call. Records how many times it was called so a test
    can assert the fast path made zero calls."""

    def __init__(self, dimensions: list[dict]) -> None:
        self._dimensions = dimensions
        self.calls = 0

    def score(self, evidence, system_prompt) -> RawJudgeScore:
        self.calls += 1
        return RawJudgeScore(dimensions=[RawDimensionScore(**d) for d in self._dimensions])
