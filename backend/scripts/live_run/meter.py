"""Counts tokens, dollars and seconds for every OpenAI call the live run makes, and stops the run at a spend cap.

The real clients in core/llm take an OpenAI object, so the run hands them a metered stand-in with the same three
methods they call. Nothing in core/ or app/ changes."""
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

# USD per million tokens, (input, output). Third-party price pages for gpt-4o (2024-08-06) and
# text-embedding-3-small; see docs/research/openai-pricing-for-live-run.md. Re-check before trusting the dollars.
PRICES_PER_MILLION = {
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
}


class BudgetExceeded(Exception):
    pass


@dataclass
class StageTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    usd: float = 0.0


@dataclass
class UsageMeter:
    cap_usd: float
    stages: dict[str, StageTotals] = field(default_factory=dict)

    @property
    def spent_usd(self) -> float:
        return sum(stage.usd for stage in self.stages.values())

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.4f}, cap is ${self.cap_usd:.2f}")

    def record(self, stage: str, model: str, input_tokens: int, output_tokens: int, seconds: float) -> None:
        price_in, price_out = PRICES_PER_MILLION[model]
        totals = self.stages.setdefault(stage, StageTotals())
        totals.calls += 1
        totals.input_tokens += input_tokens
        totals.output_tokens += output_tokens
        totals.seconds += seconds
        totals.usd += (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def _timed(meter: UsageMeter, stage: str, call, read_usage):
    def wrapper(**kwargs):
        meter.check()
        started = time.perf_counter()
        response = call(**kwargs)
        input_tokens, output_tokens = read_usage(response)
        meter.record(stage, kwargs["model"], input_tokens, output_tokens, time.perf_counter() - started)
        return response

    return wrapper


def metered_openai(client, meter: UsageMeter) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_timed(
            meter, "agent", client.chat.completions.create,
            lambda r: (r.usage.prompt_tokens, r.usage.completion_tokens),
        ))),
        responses=SimpleNamespace(parse=_timed(
            meter, "extraction", client.responses.parse, lambda r: (r.usage.input_tokens, r.usage.output_tokens),
        )),
        embeddings=SimpleNamespace(create=_timed(
            meter, "embedding", client.embeddings.create, lambda r: (r.usage.prompt_tokens, 0),
        )),
    )
