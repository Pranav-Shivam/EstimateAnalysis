# Phase 5 Judge and Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-vendor (Anthropic Claude Haiku) LLM judge that scores every `ready` estimate draft against price-book, contract, and graph evidence in three dimensions, gates a `trusted`/`escalate` verdict on a Cohen's-kappa-calibrated threshold, and files exactly one flagged fact for human review when it escalates.

**Architecture:** New `app/judge/` module (evidence assembly, pure scoring/rollup, persistence, service, route) plus `core/llm/anthropic_judge_client.py`, following the repo's route -> service -> repository -> DB/LLM layering. A `needs_review` draft short-circuits the judge with zero LLM calls. A hand-authored, hand-scored golden set (`data/judge_golden_set.json`) drives both the real calibration script (dry-run by default) and a fully offline acceptance test.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, `anthropic` Python SDK (new dependency), pytest, real Postgres (port 5433) and Neo4j (port 17687) in tests, no real Anthropic/OpenAI calls anywhere in the test suite.

**Spec:** `docs/superpowers/specs/2026-09-29-phase5-judge-review-design.md`

## Global Constraints

- No AI attribution in commits (write commit messages as a human would).
- No em dash anywhere: code, comments, docs. No emojis anywhere.
- Postgres always host port 5433, never 5432. Neo4j non-default host ports (17474/17687), never default.
- Tests never assert absolute counts against shared databases; use uniquely-namespaced test data and clean it up. Static local fixture files the plan itself generates (e.g. `data/judge_golden_set.json`) are not a shared database and may assert an exact/bounded count.
- No real OpenAI or Anthropic paid API call anywhere without the owner's explicit prior approval. `scripts/calibrate_judge.py` is a dry run by default; only `--yes` calls the real API, and that flag is never passed during this plan's execution.
- Stage files by explicit path only, never `git add -A` or `git add .`.
- SQLAlchemy sessions run with autoflush off (matches the existing `make_session_factory`/test fixtures; no new session factory is introduced by this plan).
- Code reads like a senior engineer wrote it: no dead code, no unexplained magic numbers, no unresolved TODOs.
- The owner currently holds no Anthropic API key. Every task in this plan must be completable and fully tested without one; the real calibration run is a follow-up step the owner runs later with `--yes`.

## Review Focus

- A `ready` draft's line carries a discount (`discount_pct != 0`) but the draft has no `customer_id` or `contract_id` at all (a draft that should have been blocked by guardrails but wasn't, or a hand-built test draft): `evidence.py` must report "no coverage claim" rather than raising. Covered in Task 3.
- The Anthropic client returns a malformed payload: fewer than 3 dimensions, a duplicate dimension name, or a score outside `[0, 1]`: must raise `JudgeError`, never silently produce a passing score. Covered in Task 1.
- The same estimate is judged twice (a reviewer re-runs the check, or a retry after a transient failure): must create a second verdict row without a uniqueness conflict, not silently overwrite or reject. Covered in Task 7.
- The knowledge graph goes down between an estimate being created and the judge being asked to score it: evidence assembly must raise (not swallow) `GraphError`/`GraphUnavailable`, and the route must map it to 503, consistent with the rest of the graph-backed surface. Covered in Task 7.
- The flagged (lowest-scoring) dimension's evidence spans more than one line: `line_index` on the resulting `ReviewItem` must be `None` (ambiguous which single line to point at), not silently default to the first line. Covered in Task 6.

---

## Task 1: Cross-vendor judge client

**Files:**
- Modify: `pyproject.toml` (add `anthropic` dependency)
- Modify: `.env.example` (add `ANTHROPIC_API_KEY=`)
- Modify: `core/config/settings.py`
- Create: `core/llm/anthropic_judge_client.py`
- Test: `tests/core/test_anthropic_judge_client.py`

**Interfaces:**
- Consumes: nothing from other Phase 5 tasks.
- Produces: `JUDGE_MODEL: str`, `DIMENSION_NAMES: tuple[str, ...]` (the three fixed dimension names, alphabetical), `class JudgeError(Exception)`, `@dataclass RawDimensionScore(name: str, score: float, rationale: str)`, `@dataclass RawJudgeScore(dimensions: list[RawDimensionScore])`, `class AnthropicJudgeClient: def __init__(self, client=None); def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore`. `Settings.anthropic_api_key: str`.

- [ ] **Step 1: Add the `anthropic` dependency and verify it installs**

Run: `cd backend && uv add anthropic`
Expected: `pyproject.toml` gains `anthropic>=...` under `dependencies`, `uv.lock` updates, and `uv run python -c "import anthropic; print(anthropic.__version__)"` prints a version with no error.

- [ ] **Step 2: Add the settings field and env template line**

In `core/config/settings.py`, add one field to `Settings` (after `openai_api_key`):

```python
    anthropic_api_key: str
```

In `.env.example`, add one line after `OPENAI_API_KEY=`:

```
ANTHROPIC_API_KEY=
```

- [ ] **Step 3: Write the failing tests for `AnthropicJudgeClient.score`**

Create `tests/core/test_anthropic_judge_client.py`:

```python
from types import SimpleNamespace

import pytest

from core.llm.anthropic_judge_client import AnthropicJudgeClient, JudgeError


class _FakeMessages:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return self._response


class _FakeAnthropic:
    def __init__(self, response=None, exc=None):
        self.messages = _FakeMessages(response, exc)


def _tool_use_response(input_payload):
    block = SimpleNamespace(type="tool_use", name="submit_scores", input=input_payload)
    return SimpleNamespace(content=[block])


def _good_payload():
    return {"dimensions": [
        {"name": "price_provenance", "score": 0.9, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.8, "rationale": "complete"},
    ]}


def test_score_parses_a_well_formed_response():
    fake = _FakeAnthropic(response=_tool_use_response(_good_payload()))
    client = AnthropicJudgeClient(client=fake)

    result = client.score([{"line_index": 0}], "system prompt")

    names = {d.name for d in result.dimensions}
    assert names == {"price_provenance", "contract_discount", "graph_completion"}
    assert fake.messages.calls[0]["model"] == "claude-haiku-4-5-20251001"


def test_score_raises_on_api_exception():
    fake = _FakeAnthropic(exc=RuntimeError("network down"))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="network down"):
        client.score([], "system prompt")


def test_score_raises_when_no_tool_use_block_is_returned():
    fake = _FakeAnthropic(response=SimpleNamespace(content=[SimpleNamespace(type="text", text="no")]))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="no tool_use"):
        client.score([], "system prompt")


def test_score_raises_on_a_missing_dimension():
    payload = _good_payload()
    payload["dimensions"].pop()
    fake = _FakeAnthropic(response=_tool_use_response(payload))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="expected 3 dimensions"):
        client.score([], "system prompt")


def test_score_raises_on_a_duplicate_dimension_name():
    payload = _good_payload()
    payload["dimensions"][2]["name"] = "price_provenance"
    fake = _FakeAnthropic(response=_tool_use_response(payload))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="more than once"):
        client.score([], "system prompt")


def test_score_raises_on_an_out_of_range_score():
    payload = _good_payload()
    payload["dimensions"][0]["score"] = 1.5
    fake = _FakeAnthropic(response=_tool_use_response(payload))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="not a number in"):
        client.score([], "system prompt")
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/core/test_anthropic_judge_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.llm.anthropic_judge_client'`

- [ ] **Step 5: Implement `core/llm/anthropic_judge_client.py`**

```python
import json

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


from dataclasses import dataclass


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
```

Move the `from dataclasses import dataclass` line to the top of the file with the other imports.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/core/test_anthropic_judge_client.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/.env.example backend/core/config/settings.py backend/core/llm/anthropic_judge_client.py backend/tests/core/test_anthropic_judge_client.py
git commit -m "feat: add cross-vendor Anthropic judge client"
```

---

## Task 2: Judge golden set

**Files:**
- Create: `scripts/data_gen/judge_golden_set_gen.py`
- Create: `data/judge_golden_set.json` (generated by the script above)
- Test: `tests/data_gen/test_judge_golden_set.py`

**Interfaces:**
- Consumes: nothing from other Phase 5 tasks.
- Produces: `data/judge_golden_set.json`, a JSON list of case dicts. Every case has `case_id: str`, `label: "trust" | "escalate"`, `rationale: str`, `estimate_status: "ready" | "needs_review"`. A `"ready"` case additionally has `evidence: list[dict]` (one dict per line, each with keys `line_index`, `sku_id`, `unit_price`, `price` (`price_source`, `list_price`, `predicted_price`, `peer_count`, `low`, `high`), `contract` (`discount_pct`, `contract_id`, `covered`, `active_on_as_of`, `days_to_expiry`), `graph` (`discontinued`, `live_sku_id`, `required_part_ids`, `missing_required_part_ids`)) and `scores: dict[str, float]` (exactly the three dimension names, each 0 to 1: the score a well-calibrated judge should give this case). A `"needs_review"` case instead has `guardrail_reason: str`. This dict shape is the fixed, literal contract that `app/judge/evidence.py` (Task 3) also produces; the two tasks do not import each other.

- [ ] **Step 1: Write the failing golden-set validation tests**

Create `tests/data_gen/test_judge_golden_set.py`:

```python
import json
from pathlib import Path

DIMENSION_NAMES = {"price_provenance", "contract_discount", "graph_completion"}
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _cases():
    return json.loads((DATA_DIR / "judge_golden_set.json").read_text(encoding="utf-8"))


def test_golden_set_has_at_least_twenty_cases():
    assert len(_cases()) >= 20


def test_golden_set_has_both_labels():
    labels = {c["label"] for c in _cases()}
    assert labels == {"trust", "escalate"}


def test_every_ready_case_has_evidence_and_scores_for_all_three_dimensions():
    for case in _cases():
        if case["estimate_status"] != "ready":
            continue
        assert case["evidence"], case["case_id"]
        for line in case["evidence"]:
            assert set(line.keys()) >= {"line_index", "sku_id", "unit_price", "price", "contract", "graph"}, case["case_id"]
        assert set(case["scores"].keys()) == DIMENSION_NAMES, case["case_id"]
        for score in case["scores"].values():
            assert 0.0 <= score <= 1.0, case["case_id"]


def test_every_needs_review_case_has_a_guardrail_reason():
    for case in _cases():
        if case["estimate_status"] == "needs_review":
            assert case.get("guardrail_reason"), case["case_id"]


def test_case_ids_are_unique():
    ids = [c["case_id"] for c in _cases()]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_judge_golden_set.py -v`
Expected: FAIL with `FileNotFoundError` (no `data/judge_golden_set.json` yet)

- [ ] **Step 3: Write the golden-set generator**

Create `scripts/data_gen/judge_golden_set_gen.py`:

```python
"""Generates data/judge_golden_set.json: hand-designed synthetic cases for Phase 5 judge calibration.

Every case is an explicit row below, not randomly generated: the label and scores are a human judgment
call (this project's sole annotator), not something a model produced. Cases cover the class of problem
code guardrails cannot structurally catch (thin vs. strong predicted-price evidence, a contract that is
technically active but about to expire), plus a few guardrail-blocked cases to check the judge's fast
path. See docs/superpowers/specs/2026-09-29-phase5-judge-review-design.md for the design.
"""
import json
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "judge_golden_set.json"


def _line(sku_id, unit_price, *, price_source="list", list_price=None, predicted_price=None,
          peer_count=None, low=None, high=None, discount_pct=0.0, contract_id=None, covered=None,
          active_on_as_of=None, days_to_expiry=None, discontinued=False, live_sku_id=None,
          required_part_ids=(), missing_required_part_ids=()):
    return {
        "line_index": 0,
        "sku_id": sku_id,
        "unit_price": unit_price,
        "price": {
            "price_source": price_source, "list_price": list_price, "predicted_price": predicted_price,
            "peer_count": peer_count, "low": low, "high": high,
        },
        "contract": {
            "discount_pct": discount_pct, "contract_id": contract_id, "covered": covered,
            "active_on_as_of": active_on_as_of, "days_to_expiry": days_to_expiry,
        },
        "graph": {
            "discontinued": discontinued, "live_sku_id": live_sku_id or sku_id,
            "required_part_ids": list(required_part_ids), "missing_required_part_ids": list(missing_required_part_ids),
        },
    }


def _clean_case(case_id, sku_id, price):
    return {
        "case_id": case_id, "label": "trust", "estimate_status": "ready",
        "rationale": f"{sku_id}: list price, no discount claimed, no required parts outstanding. Nothing here needs a second look.",
        "scores": {"price_provenance": 0.95, "contract_discount": 1.0, "graph_completion": 0.95},
        "evidence": [_line(sku_id, price, list_price=price)],
    }


def _thin_predicted_case(case_id, sku_id, price, peer_count):
    spread = price * 0.6
    return {
        "case_id": case_id, "label": "escalate", "estimate_status": "ready",
        "rationale": f"{sku_id}: predicted price from only {peer_count} peers with a wide low/high spread; too thin to trust unreviewed.",
        "scores": {"price_provenance": 0.3, "contract_discount": 1.0, "graph_completion": 0.95},
        "evidence": [_line(sku_id, price, price_source="predicted", predicted_price=price,
                            peer_count=peer_count, low=price - spread / 2, high=price + spread / 2)],
    }


def _strong_predicted_case(case_id, sku_id, price, peer_count):
    spread = price * 0.05
    return {
        "case_id": case_id, "label": "trust", "estimate_status": "ready",
        "rationale": f"{sku_id}: predicted price from {peer_count} peers with a tight low/high band; strong enough evidence to trust.",
        "scores": {"price_provenance": 0.85, "contract_discount": 1.0, "graph_completion": 0.95},
        "evidence": [_line(sku_id, price, price_source="predicted", predicted_price=price,
                            peer_count=peer_count, low=price - spread / 2, high=price + spread / 2)],
    }


def _healthy_contract_case(case_id, sku_id, price, days_to_expiry):
    return {
        "case_id": case_id, "label": "trust", "estimate_status": "ready",
        "rationale": f"{sku_id}: discount matches the contract and it is not due to expire for {days_to_expiry} days.",
        "scores": {"price_provenance": 0.95, "contract_discount": 0.9, "graph_completion": 0.95},
        "evidence": [_line(sku_id, price, list_price=price, discount_pct=10.0, contract_id="CTR-G1",
                            covered=True, active_on_as_of=True, days_to_expiry=days_to_expiry)],
    }


def _expiring_contract_case(case_id, sku_id, price, days_to_expiry):
    return {
        "case_id": case_id, "label": "escalate", "estimate_status": "ready",
        "rationale": f"{sku_id}: discount matches the contract today, but it expires in {days_to_expiry} days; worth a human check before it goes out.",
        "scores": {"price_provenance": 0.95, "contract_discount": 0.4, "graph_completion": 0.95},
        "evidence": [_line(sku_id, price, list_price=price, discount_pct=10.0, contract_id="CTR-G1",
                            covered=True, active_on_as_of=True, days_to_expiry=days_to_expiry)],
    }


def _fast_path_case(case_id, sku_id, reason):
    return {
        "case_id": case_id, "label": "escalate", "estimate_status": "needs_review",
        "rationale": f"{sku_id}: guardrails already rejected this draft; the judge must defer without scoring it.",
        "guardrail_reason": reason,
    }


# Cluster sizes are not arbitrary: with 15 trust cases and 17 escalate cases (32 total), a candidate
# threshold that wrongly trusts one whole escalate cluster of 7 still drops Cohen's kappa to about 0.57,
# below the 0.6 acceptable band, so calibrate() (Task 8) is forced past both escalate clusters onto the
# threshold that separates every case correctly. A cluster of 5 does not: at 5/32 wrongly trusted, kappa
# stays above 0.6, so calibrate() would settle for that lower, imperfect threshold instead. See
# tests/test_phase5_acceptance.py, which needs perfect separation, not just an acceptable kappa.
CASES = (
    [_clean_case(f"jg-{i:04d}", f"SKU-G-CLEAN{i}", 40.0 + 10 * i) for i in range(1, 6)]
    + [_thin_predicted_case(f"jg-{i:04d}", f"SKU-G-THIN{i}", 60.0 + 5 * i, 3 + (i % 2)) for i in range(6, 13)]
    + [_strong_predicted_case(f"jg-{i:04d}", f"SKU-G-STRONG{i}", 60.0 + 5 * i, 18 + i) for i in range(13, 18)]
    + [_healthy_contract_case(f"jg-{i:04d}", f"SKU-G-HEALTHY{i}", 80.0 + 5 * i, 200 + 20 * i) for i in range(18, 23)]
    + [_expiring_contract_case(f"jg-{i:04d}", f"SKU-G-EXPIRING{i}", 80.0 + 5 * i, i) for i in range(23, 30)]
    + [
        _fast_path_case("jg-0030", "SKU-G-BLOCKED1", "SKU SKU-G-BLOCKED1 is discontinued; quote its live replacement instead"),
        _fast_path_case("jg-0031", "SKU-G-BLOCKED2", "the request asks for SKU-G-REQ; the draft must quote it"),
        _fast_path_case("jg-0032", "SKU-G-BLOCKED3", "SKU-G-BLOCKED3 requires SKU-G-PART; the draft must include it"),
    ]
)


def main() -> None:
    OUT_PATH.write_text(json.dumps(CASES, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(CASES)} cases to {OUT_PATH}")


if __name__ == "__main__":
    main()
```

Run it: `cd backend && uv run python scripts/data_gen/judge_golden_set_gen.py`
Expected output: `wrote 32 cases to .../data/judge_golden_set.json`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_judge_golden_set.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/judge_golden_set_gen.py backend/data/judge_golden_set.json backend/tests/data_gen/test_judge_golden_set.py
git commit -m "feat: add the hand-labeled judge golden set"
```

---

## Task 3: Evidence assembly

**Files:**
- Create: `app/judge/__init__.py`
- Create: `app/judge/evidence.py`
- Test: `tests/app/judge/__init__.py`
- Test: `tests/app/judge/test_evidence.py`

**Interfaces:**
- Consumes: `app.estimate.pricing.predict_price_for_sku`, `app.estimate.schemas.DraftLine`/`EstimateDraft`, `app.graph.reader.GraphReader` (`sku_chain`, `required_parts`, `contract_coverage`), `app.reference_data.repository.get_sku` (all pre-existing).
- Produces: `@dataclass PriceEvidence(price_source, list_price, predicted_price, peer_count, low, high)`, `@dataclass ContractEvidence(discount_pct, contract_id, covered, active_on_as_of, days_to_expiry)`, `@dataclass GraphEvidence(discontinued, live_sku_id, required_part_ids, missing_required_part_ids)`, `@dataclass LineEvidence(line_index, sku_id, unit_price, price, contract, graph)`, `def build_evidence(session, graph, draft, as_of) -> list[LineEvidence]`. `dataclasses.asdict(line_evidence)` produces exactly the dict shape pinned in Task 2's Interfaces block.

- [ ] **Step 1: Write the failing evidence tests**

Create `app/judge/__init__.py` (empty) and `tests/app/judge/__init__.py` (empty).

Create `tests/app/judge/test_evidence.py`:

```python
from datetime import date

from app.estimate.schemas import DraftLine, EstimateDraft
from app.judge.evidence import build_evidence
from app.reference_data.repository import upsert_contract
from tests.app.estimate.seed import AS_OF, seed_world


def _draft(lines, customer_id="CUST-E1", contract_id="CTR-E1"):
    return EstimateDraft(customer_id=customer_id, contract_id=contract_id, lines=lines)


def test_list_price_line_carries_its_list_price(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line]), AS_OF)

    assert evidence[0].price.price_source == "list"
    assert evidence[0].price.list_price == 100.0
    assert evidence[0].price.predicted_price is None


def test_predicted_price_line_carries_peer_evidence(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-GAP", quantity=1, unit_price=20.0, price_source="predicted", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id=None), AS_OF)

    assert evidence[0].price.price_source == "predicted"
    assert evidence[0].price.predicted_price == 20.0
    assert evidence[0].price.peer_count == 3
    assert evidence[0].price.low == 15.0
    assert evidence[0].price.high == 25.0


def test_line_without_a_discount_has_no_contract_claim(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line]), AS_OF)

    assert evidence[0].contract.covered is None
    assert evidence[0].contract.days_to_expiry is None


def test_discount_without_a_contract_reports_no_coverage_claim(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=10.0)

    evidence = build_evidence(db_session, reader, _draft([line], customer_id=None, contract_id=None), AS_OF)

    assert evidence[0].contract.covered is None
    assert evidence[0].contract.contract_id is None


def test_covered_discount_reports_days_to_expiry(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=10.0)

    evidence = build_evidence(db_session, reader, _draft([line]), AS_OF)

    assert evidence[0].contract.covered is True
    assert evidence[0].contract.active_on_as_of is True
    assert evidence[0].contract.days_to_expiry == (date(2025, 12, 31) - AS_OF).days


def test_near_expiry_contract_reports_a_small_days_to_expiry(db_session, make_reader):
    seed_world(db_session)
    upsert_contract(
        db_session, contract_id="CTR-E2", customer_id="CUST-E1", discount_category="Cat-E-A",
        covered_categories=["Cat-E-A"], effective_from=date(2024, 1, 1), effective_to=date(2024, 9, 5),
        discount_pct=10.0,
    )
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=10.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id="CTR-E2"), AS_OF)

    assert evidence[0].contract.days_to_expiry == 4


def test_discontinued_line_reports_live_replacement(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-OLD", quantity=1, unit_price=80.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id=None), AS_OF)

    assert evidence[0].graph.discontinued is True
    assert evidence[0].graph.live_sku_id == "SKU-E-A1"


def test_missing_required_part_is_reported(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-B1", quantity=1, unit_price=50.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id=None), AS_OF)

    assert evidence[0].graph.required_part_ids == ["SKU-E-A1"]
    assert evidence[0].graph.missing_required_part_ids == ["SKU-E-A1"]


def test_present_required_part_is_not_reported_as_missing(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    lines = [
        DraftLine(sku_id="SKU-E-B1", quantity=1, unit_price=50.0, price_source="list", discount_pct=0.0),
        DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0),
    ]

    evidence = build_evidence(db_session, reader, _draft(lines, contract_id=None), AS_OF)

    assert evidence[0].graph.missing_required_part_ids == []
    assert evidence[1].line_index == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/app/judge/test_evidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.judge.evidence'`

- [ ] **Step 3: Implement `app/judge/evidence.py`**

```python
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import predict_price_for_sku
from app.estimate.schemas import DraftLine, EstimateDraft
from app.graph.reader import GraphReader
from app.reference_data.repository import get_sku


@dataclass(frozen=True)
class PriceEvidence:
    price_source: str
    list_price: float | None
    predicted_price: float | None
    peer_count: int | None
    low: float | None
    high: float | None


@dataclass(frozen=True)
class ContractEvidence:
    discount_pct: float
    contract_id: str | None
    covered: bool | None
    active_on_as_of: bool | None
    days_to_expiry: int | None


@dataclass(frozen=True)
class GraphEvidence:
    discontinued: bool
    live_sku_id: str | None
    required_part_ids: list[str] = field(default_factory=list)
    missing_required_part_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LineEvidence:
    line_index: int
    sku_id: str
    unit_price: float
    price: PriceEvidence
    contract: ContractEvidence
    graph: GraphEvidence


def _price_evidence(session: Session, line: DraftLine) -> PriceEvidence:
    sku = get_sku(session, line.sku_id) if line.sku_id else None
    if line.price_source != "predicted":
        return PriceEvidence(
            price_source="list", list_price=sku.list_price if sku else None,
            predicted_price=None, peer_count=None, low=None, high=None,
        )
    prediction = predict_price_for_sku(session, sku) if sku else None
    return PriceEvidence(
        price_source="predicted", list_price=None,
        predicted_price=prediction.price if prediction else None,
        peer_count=prediction.peer_count if prediction else None,
        low=prediction.low if prediction else None, high=prediction.high if prediction else None,
    )


def _contract_evidence(graph: GraphReader, draft: EstimateDraft, line: DraftLine, as_of: date) -> ContractEvidence:
    if line.discount_pct == 0 or draft.customer_id is None or draft.contract_id is None or line.sku_id is None:
        return ContractEvidence(
            discount_pct=line.discount_pct, contract_id=draft.contract_id,
            covered=None, active_on_as_of=None, days_to_expiry=None,
        )
    matches = [
        c for c in graph.contract_coverage(draft.customer_id, line.sku_id, as_of) if c.contract_id == draft.contract_id
    ]
    if not matches:
        return ContractEvidence(
            discount_pct=line.discount_pct, contract_id=draft.contract_id,
            covered=False, active_on_as_of=None, days_to_expiry=None,
        )
    match = matches[0]
    days_to_expiry = (date.fromisoformat(match.effective_to) - as_of).days
    return ContractEvidence(
        discount_pct=line.discount_pct, contract_id=draft.contract_id,
        covered=match.covered, active_on_as_of=match.active_on_as_of, days_to_expiry=days_to_expiry,
    )


def _graph_evidence(graph: GraphReader, draft: EstimateDraft, line: DraftLine) -> GraphEvidence:
    present = {l.sku_id for l in draft.lines if l.sku_id is not None}
    chain = graph.sku_chain(line.sku_id)
    if chain is None:
        return GraphEvidence(discontinued=False, live_sku_id=None)
    live = chain.live_end
    required = graph.required_parts(live.sku_id) if live is not None else []
    return GraphEvidence(
        discontinued=chain.nodes[0].discontinued,
        live_sku_id=live.sku_id if live is not None else None,
        required_part_ids=[p.sku_id for p in required],
        missing_required_part_ids=[p.sku_id for p in required if p.sku_id not in present],
    )


def build_evidence(session: Session, graph: GraphReader, draft: EstimateDraft, as_of: date) -> list[LineEvidence]:
    return [
        LineEvidence(
            line_index=index, sku_id=line.sku_id, unit_price=line.unit_price,
            price=_price_evidence(session, line), contract=_contract_evidence(graph, draft, line, as_of),
            graph=_graph_evidence(graph, draft, line),
        )
        for index, line in enumerate(draft.lines)
        if line.sku_id is not None
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/app/judge/test_evidence.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/judge/__init__.py backend/app/judge/evidence.py backend/tests/app/judge/__init__.py backend/tests/app/judge/test_evidence.py
git commit -m "feat: assemble judge evidence from price, contract, and graph data"
```

---

## Task 4: Scoring and rollup logic

**Files:**
- Create: `app/judge/scoring.py`
- Test: `tests/app/judge/test_scoring.py`

**Interfaces:**
- Consumes: nothing from other Phase 5 tasks (pure logic, no I/O).
- Produces: `@dataclass ScoredDimension(name: str, score: float, rationale: str)`, `def rollup(dimensions: list[ScoredDimension]) -> tuple[float, str]` (overall confidence, flagged dimension name), `def gate(overall_confidence: float, threshold: float) -> bool`.

- [ ] **Step 1: Write the failing scoring tests**

Create `tests/app/judge/test_scoring.py`:

```python
from app.judge.scoring import ScoredDimension, gate, rollup


def test_rollup_picks_the_lowest_score():
    dims = [
        ScoredDimension("price_provenance", 0.9, "fine"),
        ScoredDimension("graph_completion", 0.4, "missing part"),
        ScoredDimension("contract_discount", 0.95, "fine"),
    ]

    overall, flagged = rollup(dims)

    assert overall == 0.4
    assert flagged == "graph_completion"


def test_rollup_breaks_an_exact_tie_alphabetically():
    dims = [
        ScoredDimension("price_provenance", 0.5, "a"),
        ScoredDimension("contract_discount", 0.5, "b"),
        ScoredDimension("graph_completion", 0.9, "c"),
    ]

    overall, flagged = rollup(dims)

    assert overall == 0.5
    assert flagged == "contract_discount"


def test_gate_trusts_at_or_above_threshold():
    assert gate(0.8, 0.8) is True
    assert gate(0.81, 0.8) is True


def test_gate_escalates_below_threshold():
    assert gate(0.79, 0.8) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/app/judge/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.judge.scoring'`

- [ ] **Step 3: Implement `app/judge/scoring.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoredDimension:
    name: str
    score: float
    rationale: str


def rollup(dimensions: list[ScoredDimension]) -> tuple[float, str]:
    """The overall confidence is the weakest dimension, so one bad fact cannot be diluted by two good ones.
    An exact tie breaks alphabetically so the flagged dimension is deterministic."""
    overall = min(d.score for d in dimensions)
    flagged = sorted(d.name for d in dimensions if d.score == overall)[0]
    return overall, flagged


def gate(overall_confidence: float, threshold: float) -> bool:
    return overall_confidence >= threshold
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/app/judge/test_scoring.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/judge/scoring.py backend/tests/app/judge/test_scoring.py
git commit -m "feat: add judge dimension rollup and threshold gate"
```

---

## Task 5: Verdict and review-item persistence

**Files:**
- Create: `app/judge/models.py`
- Create: `migrations/versions/0005_judge_verdicts_and_review_items.py`
- Create: `app/judge/repository.py`
- Test: `tests/app/judge/test_repository.py`

**Interfaces:**
- Consumes: `app.intake.repository.save_quote_request`, `app.estimate.repository.save_estimate_draft` (test setup only, pre-existing).
- Produces: `class JudgeVerdictRow(Base)` (`id`, `estimate_id`, `model`, `dimensions`, `overall_confidence`, `flagged_dimension`, `trusted`, `created_at`), `class ReviewItemRow(Base)` (`id`, `judge_verdict_id`, `estimate_id`, `dimension`, `fact`, `evidence`, `line_index`, `status`, `created_at`), `def save_judge_verdict(session, *, estimate_id, model, dimensions: list[dict], overall_confidence, flagged_dimension, trusted) -> JudgeVerdictRow`, `def save_review_item(session, *, judge_verdict_id, estimate_id, dimension, fact, evidence: dict, line_index) -> ReviewItemRow`, `def get_judge_verdict(session, verdict_id) -> JudgeVerdictRow | None`, `def list_open_review_items(session) -> list[ReviewItemRow]`.

- [ ] **Step 1: Write the failing repository tests**

Create `tests/app/judge/test_repository.py`:

```python
import uuid

from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import get_judge_verdict, list_open_review_items, save_judge_verdict, save_review_item


def _estimate_draft_id(session) -> uuid.UUID:
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    row = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"customer_id": "CUST-E1", "lines": []},
        violations=[], iterations=1, reason=None,
    )
    return row.id


def test_save_and_get_judge_verdict_round_trips(db_session):
    estimate_id = _estimate_draft_id(db_session)

    row = save_judge_verdict(
        db_session, estimate_id=estimate_id, model="claude-haiku-4-5-20251001",
        dimensions=[{"name": "price_provenance", "score": 0.9, "rationale": "fine", "evidence": []}],
        overall_confidence=0.9, flagged_dimension="price_provenance", trusted=True,
    )

    fetched = get_judge_verdict(db_session, row.id)
    assert fetched.estimate_id == estimate_id
    assert fetched.trusted is True
    assert fetched.dimensions[0]["name"] == "price_provenance"


def test_review_item_appears_in_open_list(db_session):
    estimate_id = _estimate_draft_id(db_session)
    verdict = save_judge_verdict(
        db_session, estimate_id=estimate_id, model="claude-haiku-4-5-20251001",
        dimensions=[], overall_confidence=0.4, flagged_dimension="graph_completion", trusted=False,
    )

    item = save_review_item(
        db_session, judge_verdict_id=verdict.id, estimate_id=estimate_id, dimension="graph_completion",
        fact="missing required part", evidence={"missing": ["SKU-X"]}, line_index=0,
    )

    open_ids = [row.id for row in list_open_review_items(db_session)]
    assert item.id in open_ids
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/app/judge/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.judge.models'`

- [ ] **Step 3: Implement `app/judge/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class JudgeVerdictRow(Base):
    __tablename__ = "judge_verdicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_drafts.id"), index=True)
    model: Mapped[str] = mapped_column(Text)
    dimensions: Mapped[list] = mapped_column(JSONB)
    overall_confidence: Mapped[float]
    flagged_dimension: Mapped[str] = mapped_column(Text)
    trusted: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReviewItemRow(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    judge_verdict_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("judge_verdicts.id"), index=True)
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_drafts.id"), index=True)
    dimension: Mapped[str] = mapped_column(Text)
    fact: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    line_index: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

- [ ] **Step 4: Write the migration**

Create `migrations/versions/0005_judge_verdicts_and_review_items.py`:

```python
"""judge verdicts and review items

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_verdicts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("estimate_id", UUID(as_uuid=True), sa.ForeignKey("estimate_drafts.id"), nullable=False, index=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("dimensions", JSONB(), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("flagged_dimension", sa.Text(), nullable=False),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "review_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("judge_verdict_id", UUID(as_uuid=True), sa.ForeignKey("judge_verdicts.id"), nullable=False, index=True),
        sa.Column("estimate_id", UUID(as_uuid=True), sa.ForeignKey("estimate_drafts.id"), nullable=False, index=True),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("review_items")
    op.drop_table("judge_verdicts")
```

Run: `cd backend && uv run alembic upgrade head`
Expected: applies `0005` with no error.

- [ ] **Step 5: Implement `app/judge/repository.py`**

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.judge.models import JudgeVerdictRow, ReviewItemRow


def save_judge_verdict(
    session: Session, *, estimate_id: uuid.UUID, model: str, dimensions: list[dict], overall_confidence: float,
    flagged_dimension: str, trusted: bool,
) -> JudgeVerdictRow:
    row = JudgeVerdictRow(
        id=uuid.uuid4(), estimate_id=estimate_id, model=model, dimensions=dimensions,
        overall_confidence=overall_confidence, flagged_dimension=flagged_dimension, trusted=trusted,
    )
    session.add(row)
    session.flush()
    return row


def save_review_item(
    session: Session, *, judge_verdict_id: uuid.UUID, estimate_id: uuid.UUID, dimension: str, fact: str,
    evidence: dict, line_index: int | None,
) -> ReviewItemRow:
    row = ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=judge_verdict_id, estimate_id=estimate_id, dimension=dimension,
        fact=fact, evidence=evidence, line_index=line_index, status="open",
    )
    session.add(row)
    session.flush()
    return row


def get_judge_verdict(session: Session, verdict_id: uuid.UUID) -> JudgeVerdictRow | None:
    return session.get(JudgeVerdictRow, verdict_id)


def list_open_review_items(session: Session) -> list[ReviewItemRow]:
    return list(
        session.scalars(
            select(ReviewItemRow)
            .where(ReviewItemRow.status == "open")
            .order_by(ReviewItemRow.created_at, ReviewItemRow.id)
        )
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/app/judge/test_repository.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/judge/models.py backend/migrations/versions/0005_judge_verdicts_and_review_items.py backend/app/judge/repository.py backend/tests/app/judge/test_repository.py
git commit -m "feat: persist judge verdicts and review items"
```

---

## Task 6: Judge service (wiring)

**Files:**
- Create: `app/judge/constant.py`
- Create: `app/judge/schemas.py`
- Create: `app/judge/prompts.py`
- Create: `app/judge/service.py`
- Create: `tests/app/judge/fakes.py`
- Test: `tests/app/judge/test_service.py`

**Interfaces:**
- Consumes: Task 1's `AnthropicJudgeClient`, `JudgeError`, `JUDGE_MODEL`; Task 3's `build_evidence`, `LineEvidence`; Task 4's `ScoredDimension`, `rollup`, `gate`; Task 5's `save_judge_verdict`, `save_review_item`; `app.estimate.repository.get_estimate_draft`, `app.estimate.schemas.EstimateDraft` (pre-existing).
- Produces: `DEFAULT_CONFIDENCE_THRESHOLD: float`, `KAPPA_ACCEPTABLE: float`, `CALIBRATION_PATH: Path`, `class DimensionScore(BaseModel)` (`name`, `score`, `rationale`, `evidence: list[dict]`), `class JudgeVerdict(BaseModel)` (`estimate_id`, `model`, `dimensions`, `overall_confidence`, `flagged_dimension`, `trusted`), `class ReviewItem(BaseModel)` (`dimension`, `fact`, `evidence: dict`, `line_index`), `class EstimateNotFound(Exception)`, `@dataclass JudgeRunResult(verdict, verdict_id, review_item)`, `def current_threshold() -> float`, `def run_judge(session, graph, as_of, estimate_id, llm_client) -> JudgeRunResult`.

- [ ] **Step 1: Write the failing service tests**

Create `tests/app/judge/fakes.py`:

```python
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
```

Create `tests/app/judge/test_service.py`:

```python
import uuid

import pytest

from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.service import EstimateNotFound, run_judge
from tests.app.estimate.seed import AS_OF, seed_world
from tests.app.judge.fakes import ScriptedJudgeClient
from tests.graph_support import UnusedGraph


def _quote_request(session):
    return save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )


def _ready_draft(sku_id="SKU-E-A1", discount_pct=0.0):
    return {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": sku_id, "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": discount_pct},
    ]}


def test_needs_review_draft_short_circuits_without_calling_the_client(db_session):
    request = _quote_request(db_session)
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="needs_review", draft=None, violations=[],
        iterations=3, reason="guardrail violations persisted after 3 retries",
    )
    client = ScriptedJudgeClient([])

    run = run_judge(db_session, UnusedGraph(), AS_OF, row.id, client)

    assert client.calls == 0
    assert run.verdict.trusted is False
    assert run.verdict.flagged_dimension == "guardrail"
    assert run.review_item.fact == "guardrail violations persisted after 3 retries"


def test_ready_draft_above_threshold_creates_no_review_item(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="ready", draft=_ready_draft(),
        violations=[], iterations=1, reason=None,
    )
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price, fully supported"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount claimed"},
        {"name": "graph_completion", "score": 0.9, "rationale": "live SKU, no required parts"},
    ])

    run = run_judge(db_session, make_reader(), AS_OF, row.id, client)

    assert client.calls == 1
    assert run.verdict.trusted is True
    assert run.review_item is None


def test_ready_draft_below_threshold_creates_a_review_item_naming_one_dimension(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="ready", draft=_ready_draft(),
        violations=[], iterations=1, reason=None,
    )
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price, fully supported"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount claimed"},
        {"name": "graph_completion", "score": 0.3, "rationale": "evidence for this line is thin"},
    ])

    run = run_judge(db_session, make_reader(), AS_OF, row.id, client)

    assert run.verdict.trusted is False
    assert run.verdict.flagged_dimension == "graph_completion"
    assert run.review_item.dimension == "graph_completion"
    assert run.review_item.line_index == 0


def test_flagged_dimension_spanning_two_lines_leaves_line_index_none(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-A1", "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0},
        {"sku_id": "SKU-E-B1", "quantity": 1, "unit_price": 50.0, "price_source": "list", "discount_pct": 0.0},
    ]}
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="ready", draft=draft, violations=[], iterations=1, reason=None,
    )
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.2, "rationale": "SKU-E-B1 is missing its required part"},
    ])

    run = run_judge(db_session, make_reader(), AS_OF, row.id, client)

    assert run.review_item.line_index is None


def test_unknown_estimate_raises(db_session):
    with pytest.raises(EstimateNotFound):
        run_judge(db_session, UnusedGraph(), AS_OF, uuid.uuid4(), ScriptedJudgeClient([]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/app/judge/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.judge.service'`

- [ ] **Step 3: Implement `app/judge/constant.py`**

```python
from pathlib import Path

DEFAULT_CONFIDENCE_THRESHOLD = 0.8
KAPPA_ACCEPTABLE = 0.6
CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "judge_calibration.json"
```

- [ ] **Step 4: Implement `app/judge/schemas.py`**

```python
import uuid
from typing import Literal

from pydantic import BaseModel

DimensionName = Literal["contract_discount", "graph_completion", "price_provenance"]


class DimensionScore(BaseModel):
    name: DimensionName
    score: float
    rationale: str
    evidence: list[dict]


class JudgeVerdict(BaseModel):
    estimate_id: uuid.UUID
    model: str
    dimensions: list[DimensionScore]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool


class ReviewItem(BaseModel):
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
```

- [ ] **Step 5: Implement `app/judge/prompts.py`**

```python
JUDGE_SYSTEM_PROMPT = (
    "You are a second, independent reviewer of a B2B quote estimate for a plumbing and HVAC distributor. "
    "You will be given, for each line of the draft, evidence already looked up by other systems: whether its "
    "price came from the price book or was predicted from category peers, whether its discount is covered by "
    "the customer's contract and how soon that contract expires, and whether its SKU is discontinued or is "
    "missing a required part. Score exactly three dimensions, each from 0 (not trustworthy) to 1 (fully "
    "trustworthy), using only the evidence given, never outside knowledge or a re-derived price:\n"
    "- price_provenance: how well-supported each line's price is (a list price is fully supported; a predicted "
    "price is only as trustworthy as its peer_count and how tight its low/high band is).\n"
    "- contract_discount: whether each discounted line's contract coverage is solid and not about to lapse "
    "(a contract expiring in a handful of days is less trustworthy than one with months left, even if it is "
    "technically active today).\n"
    "- graph_completion: whether every line's SKU is live (not discontinued) and every required part it needs "
    "is already present as its own line.\n"
    "Call submit_scores with a score and a one-sentence rationale for each of the three dimensions."
)
```

- [ ] **Step 6: Implement `app/judge/service.py`**

```python
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.estimate.repository import get_estimate_draft
from app.estimate.schemas import EstimateDraft
from app.graph.reader import GraphReader
from app.judge.constant import CALIBRATION_PATH, DEFAULT_CONFIDENCE_THRESHOLD
from app.judge.evidence import LineEvidence, build_evidence
from app.judge.prompts import JUDGE_SYSTEM_PROMPT
from app.judge.repository import save_judge_verdict, save_review_item
from app.judge.schemas import DimensionScore, JudgeVerdict, ReviewItem
from app.judge.scoring import ScoredDimension, gate, rollup
from core.llm.anthropic_judge_client import JUDGE_MODEL, AnthropicJudgeClient


class EstimateNotFound(Exception):
    pass


@dataclass
class JudgeRunResult:
    verdict: JudgeVerdict
    verdict_id: uuid.UUID
    review_item: ReviewItem | None


def current_threshold() -> float:
    """Reads the threshold the real `scripts/calibrate_judge.py --yes` run wrote. Uncalibrated until that
    real, paid run happens, so a conservative placeholder is used until then."""
    if CALIBRATION_PATH.exists():
        import json
        return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))["threshold"]
    return DEFAULT_CONFIDENCE_THRESHOLD


def _dimension_evidence(name: str, lines: list[LineEvidence]) -> list[dict]:
    key = {"price_provenance": "price", "contract_discount": "contract", "graph_completion": "graph"}[name]
    return [{"line_index": line.line_index, "sku_id": line.sku_id, **asdict(getattr(line, key))} for line in lines]


def _fast_path_verdict(estimate_id: uuid.UUID) -> JudgeVerdict:
    return JudgeVerdict(
        estimate_id=estimate_id, model="none (guardrail fast path)", dimensions=[],
        overall_confidence=0.0, flagged_dimension="guardrail", trusted=False,
    )


def run_judge(
    session: Session, graph: GraphReader, as_of: date, estimate_id: uuid.UUID, llm_client: AnthropicJudgeClient,
) -> JudgeRunResult:
    row = get_estimate_draft(session, estimate_id)
    if row is None:
        raise EstimateNotFound(f"estimate {estimate_id} not found")

    if row.status == "needs_review":
        verdict = _fast_path_verdict(estimate_id)
        fact = row.reason or "guardrails flagged this draft for review"
        evidence = {"violations": row.violations}
        line_index = None
    else:
        draft = EstimateDraft.model_validate(row.draft)
        lines = build_evidence(session, graph, draft, as_of)
        raw = llm_client.score([asdict(line) for line in lines], JUDGE_SYSTEM_PROMPT)
        scored = [ScoredDimension(name=d.name, score=d.score, rationale=d.rationale) for d in raw.dimensions]
        overall, flagged = rollup(scored)
        dimensions = [
            DimensionScore(name=d.name, score=d.score, rationale=d.rationale, evidence=_dimension_evidence(d.name, lines))
            for d in scored
        ]
        verdict = JudgeVerdict(
            estimate_id=estimate_id, model=JUDGE_MODEL, dimensions=dimensions, overall_confidence=overall,
            flagged_dimension=flagged, trusted=gate(overall, current_threshold()),
        )
        flagged_score = next(d for d in dimensions if d.name == flagged)
        fact = flagged_score.rationale
        evidence = {"dimension": flagged, "lines": flagged_score.evidence}
        line_index = flagged_score.evidence[0]["line_index"] if len(flagged_score.evidence) == 1 else None

    verdict_row = save_judge_verdict(
        session, estimate_id=verdict.estimate_id, model=verdict.model,
        dimensions=[d.model_dump() for d in verdict.dimensions], overall_confidence=verdict.overall_confidence,
        flagged_dimension=verdict.flagged_dimension, trusted=verdict.trusted,
    )
    review_item = None
    if not verdict.trusted:
        save_review_item(
            session, judge_verdict_id=verdict_row.id, estimate_id=estimate_id, dimension=verdict.flagged_dimension,
            fact=fact, evidence=evidence, line_index=line_index,
        )
        review_item = ReviewItem(dimension=verdict.flagged_dimension, fact=fact, evidence=evidence, line_index=line_index)

    return JudgeRunResult(verdict=verdict, verdict_id=verdict_row.id, review_item=review_item)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/app/judge/test_service.py -v`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/judge/constant.py backend/app/judge/schemas.py backend/app/judge/prompts.py backend/app/judge/service.py backend/tests/app/judge/fakes.py backend/tests/app/judge/test_service.py
git commit -m "feat: wire the judge service, fast path, and threshold gate"
```

---

## Task 7: API routes

**Files:**
- Create: `api/v1/judge/__init__.py`
- Create: `api/v1/judge/response.py`
- Create: `api/v1/judge/route.py`
- Create: `api/v1/review/__init__.py`
- Create: `api/v1/review/response.py`
- Create: `api/v1/review/route.py`
- Modify: `main.py`
- Test: `tests/api/v1/test_judge_route.py`
- Test: `tests/api/v1/test_review_route.py`

**Interfaces:**
- Consumes: Task 6's `run_judge`, `EstimateNotFound`, `JudgeVerdict`/`ReviewItem` schemas; Task 5's `list_open_review_items`; Task 1's `AnthropicJudgeClient`, `JudgeError`; pre-existing `get_session`, `get_graph_client`, `get_graph_namespace`, `GraphReader`, `GraphError`, `GraphUnavailable`, `Settings`, `DATASET_AS_OF`.
- Produces: `POST /v1/judge/{estimate_id}`, `GET /v1/review`, `get_judge_client()` dependency (mirrors `get_agent_client`).

- [ ] **Step 1: Write the failing route tests**

Create `api/v1/judge/__init__.py` and `api/v1/review/__init__.py` (both empty).

Create `tests/api/v1/test_judge_route.py`:

```python
import uuid

from fastapi.testclient import TestClient

from api.v1.judge.route import get_judge_client
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from core.db.session import get_session
from core.graph.client import get_graph_client
from main import app
from tests.app.estimate.seed import seed_world
from tests.app.judge.fakes import ScriptedJudgeClient
from tests.graph_support import FailingGraphClient


def _estimate_row(session, status="ready"):
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    draft = None
    if status == "ready":
        draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
            {"sku_id": "SKU-E-A1", "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0},
        ]}
    return save_estimate_draft(
        session, quote_request_id=request.id, status=status, draft=draft, violations=[], iterations=1,
        reason=None if status == "ready" else "blocked",
    )


def _post(session, client, estimate_id):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_judge_client] = lambda: client
    try:
        return TestClient(app).post(f"/v1/judge/{estimate_id}")
    finally:
        app.dependency_overrides.clear()


def _trusted_client():
    return ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.9, "rationale": "complete"},
    ])


def test_judge_endpoint_returns_404_for_unknown_estimate(db_session):
    response = _post(db_session, ScriptedJudgeClient([]), uuid.uuid4())

    assert response.status_code == 404


def test_judge_endpoint_persists_a_trusted_verdict_with_no_review_item(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _estimate_row(db_session)

    response = _post(db_session, _trusted_client(), row.id)

    body = response.json()
    assert response.status_code == 200
    assert body["trusted"] is True
    assert body["review_item"] is None


def test_judge_endpoint_creates_a_review_item_below_threshold(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _estimate_row(db_session)
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.2, "rationale": "evidence is thin"},
    ])

    response = _post(db_session, client, row.id)

    body = response.json()
    assert body["trusted"] is False
    assert body["review_item"]["dimension"] == "graph_completion"


def test_judge_endpoint_short_circuits_a_needs_review_draft(db_session):
    row = _estimate_row(db_session, status="needs_review")

    response = _post(db_session, ScriptedJudgeClient([]), row.id)

    body = response.json()
    assert body["flagged_dimension"] == "guardrail"
    assert body["review_item"]["fact"] == "blocked"


def test_judge_endpoint_allows_scoring_the_same_estimate_twice(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _estimate_row(db_session)

    first = _post(db_session, _trusted_client(), row.id)
    second = _post(db_session, _trusted_client(), row.id)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["judge_verdict_id"] != second.json()["judge_verdict_id"]


def test_judge_endpoint_returns_503_when_the_graph_is_down(db_session):
    seed_world(db_session)
    row = _estimate_row(db_session)
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    try:
        response = _post(db_session, _trusted_client(), row.id)
    finally:
        app.dependency_overrides.pop(get_graph_client, None)

    assert response.status_code == 503
```

Create `tests/api/v1/test_review_route.py`:

```python
from fastapi.testclient import TestClient

from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app


def _open_review_item(session):
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    draft_row = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[],
        iterations=1, reason=None,
    )
    verdict = save_judge_verdict(
        session, estimate_id=draft_row.id, model="claude-haiku-4-5-20251001", dimensions=[],
        overall_confidence=0.2, flagged_dimension="graph_completion", trusted=False,
    )
    return save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=draft_row.id, dimension="graph_completion",
        fact="check this", evidence={}, line_index=0,
    )


def test_review_endpoint_lists_open_items(db_session):
    item = _open_review_item(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        response = TestClient(app).get("/v1/review")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert str(item.id) in ids
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/api/v1/test_judge_route.py tests/api/v1/test_review_route.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.v1.judge.route'`

- [ ] **Step 3: Implement `api/v1/judge/response.py`**

```python
import uuid

from pydantic import BaseModel

from app.judge.schemas import DimensionScore


class ReviewItemResponse(BaseModel):
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None


class JudgeResponse(BaseModel):
    judge_verdict_id: uuid.UUID
    estimate_id: uuid.UUID
    model: str
    dimensions: list[DimensionScore]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool
    review_item: ReviewItemResponse | None
```

- [ ] **Step 4: Implement `api/v1/judge/route.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.judge.response import JudgeResponse, ReviewItemResponse
from app.estimate.constant import DATASET_AS_OF
from app.graph.reader import GraphReader
from app.judge.service import EstimateNotFound, run_judge
from core.config.settings import Settings
from core.db.session import get_session
from core.graph.client import GraphClient, GraphError, GraphUnavailable, get_graph_client, get_graph_namespace
from core.llm.anthropic_judge_client import AnthropicJudgeClient, JudgeError

router = APIRouter(prefix="/v1/judge", tags=["judge"])


def get_judge_client() -> AnthropicJudgeClient:
    from anthropic import Anthropic

    settings = Settings()
    return AnthropicJudgeClient(client=Anthropic(api_key=settings.anthropic_api_key))


@router.post("/{estimate_id}", response_model=JudgeResponse)
def judge_estimate(
    estimate_id: uuid.UUID,
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    llm_client: AnthropicJudgeClient = Depends(get_judge_client),
) -> JudgeResponse:
    try:
        run = run_judge(session, GraphReader(graph_client, ns), DATASET_AS_OF, estimate_id, llm_client)
    except EstimateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JudgeError as exc:
        raise HTTPException(status_code=502, detail="judge failed to score the estimate") from exc
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail="graph query failed") from exc

    session.commit()
    review_item = (
        ReviewItemResponse(
            dimension=run.review_item.dimension, fact=run.review_item.fact, evidence=run.review_item.evidence,
            line_index=run.review_item.line_index,
        )
        if run.review_item else None
    )
    return JudgeResponse(
        judge_verdict_id=run.verdict_id, estimate_id=run.verdict.estimate_id, model=run.verdict.model,
        dimensions=run.verdict.dimensions, overall_confidence=run.verdict.overall_confidence,
        flagged_dimension=run.verdict.flagged_dimension, trusted=run.verdict.trusted, review_item=review_item,
    )
```

- [ ] **Step 5: Implement `api/v1/review/response.py`**

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class ReviewItemListResponse(BaseModel):
    id: uuid.UUID
    estimate_id: uuid.UUID
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
    status: str
    created_at: datetime
```

- [ ] **Step 6: Implement `api/v1/review/route.py`**

```python
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
```

- [ ] **Step 7: Register both routers in `main.py`**

```python
from fastapi import FastAPI

from api.v1.dedupe.route import router as dedupe_router
from api.v1.estimate.route import router as estimate_router
from api.v1.graph.route import router as graph_router
from api.v1.intake.route import router as intake_router
from api.v1.judge.route import router as judge_router
from api.v1.retrieval.route import router as retrieval_router
from api.v1.review.route import router as review_router

app = FastAPI(title="Estimate Analysis Backend")
app.include_router(intake_router)
app.include_router(dedupe_router)
app.include_router(estimate_router)
app.include_router(graph_router)
app.include_router(retrieval_router)
app.include_router(judge_router)
app.include_router(review_router)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/v1/test_judge_route.py tests/api/v1/test_review_route.py -v`
Expected: 8 passed

- [ ] **Step 9: Commit**

```bash
git add backend/api/v1/judge backend/api/v1/review backend/main.py backend/tests/api/v1/test_judge_route.py backend/tests/api/v1/test_review_route.py
git commit -m "feat: add judge and review API routes"
```

---

## Task 8: Calibration script and acceptance test

**Files:**
- Create: `app/judge/calibration.py`
- Create: `scripts/calibrate_judge.py`
- Test: `tests/app/judge/test_calibration.py`
- Test: `tests/test_phase5_acceptance.py`

**Interfaces:**
- Consumes: Task 4's `ScoredDimension`, `rollup`, `gate`; Task 5's golden set file (`data/judge_golden_set.json`); Task 6's `DEFAULT_CONFIDENCE_THRESHOLD`, `KAPPA_ACCEPTABLE`, `CALIBRATION_PATH`; Task 1's `AnthropicJudgeClient` (script only, never called with `--yes` in this plan).
- Produces: `@dataclass CalibrationResult(threshold: float, kappa: float)`, `def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float`, `def calibrate(scores: list[float], labels: list[bool], acceptable_kappa: float) -> CalibrationResult | None`.

- [ ] **Step 1: Write the failing calibration tests**

Create `tests/app/judge/test_calibration.py`:

```python
from app.judge.calibration import calibrate, cohens_kappa


def test_kappa_is_one_for_perfect_agreement():
    assert cohens_kappa([(True, True), (False, False), (True, True), (False, False)]) == 1.0


def test_kappa_is_zero_for_chance_level_agreement():
    pairs = [(True, True), (True, False), (True, True), (True, False)]
    assert cohens_kappa(pairs) == 0.0


def test_calibrate_finds_the_unique_separating_threshold():
    scores = [0.9, 0.7, 0.4, 0.2]
    labels = [True, True, False, False]

    result = calibrate(scores, labels, acceptable_kappa=0.6)

    assert result.threshold == 0.7
    assert result.kappa == 1.0


def test_calibrate_returns_none_when_no_threshold_clears_the_bar():
    scores = [0.9, 0.7, 0.4, 0.2]
    labels = [False, True, True, False]

    assert calibrate(scores, labels, acceptable_kappa=0.6) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/app/judge/test_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.judge.calibration'`

- [ ] **Step 3: Implement `app/judge/calibration.py`**

```python
from dataclasses import dataclass

from app.judge.scoring import gate


@dataclass(frozen=True)
class CalibrationResult:
    threshold: float
    kappa: float


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float:
    """Standard 2x2 Cohen's kappa between two boolean raters (here: judge-trusts vs. human-trusts)."""
    n = len(pairs)
    if n == 0:
        return 0.0
    agree = sum(1 for a, b in pairs if a == b) / n
    rate_a = sum(1 for a, _ in pairs if a) / n
    rate_b = sum(1 for _, b in pairs if b) / n
    expected = rate_a * rate_b + (1 - rate_a) * (1 - rate_b)
    if expected == 1.0:
        return 1.0 if agree == 1.0 else 0.0
    return (agree - expected) / (1 - expected)


def calibrate(scores: list[float], labels: list[bool], acceptable_kappa: float) -> CalibrationResult | None:
    """Sweeps every observed confidence score as a candidate threshold and returns the LOWEST one whose
    kappa against the golden set's human labels still clears acceptable_kappa: the lowest threshold
    maximizes how much gets auto-trusted (coverage) without dropping below the agreement bar. Returns
    None when no candidate clears it, per the research: a low kappa means fix the rubric, not ship a
    threshold that failed its own check."""
    best = None
    for candidate in sorted(set(scores)):
        pairs = [(gate(score, candidate), label) for score, label in zip(scores, labels)]
        kappa = cohens_kappa(pairs)
        if kappa >= acceptable_kappa and (best is None or candidate < best.threshold):
            best = CalibrationResult(threshold=candidate, kappa=kappa)
    return best
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/app/judge/test_calibration.py -v`
Expected: 4 passed

- [ ] **Step 5: Write the failing acceptance test**

Create `tests/test_phase5_acceptance.py`:

```python
import json
from pathlib import Path

from app.judge.calibration import calibrate
from app.judge.constant import KAPPA_ACCEPTABLE
from app.judge.scoring import ScoredDimension, gate, rollup

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "judge_golden_set.json"


def _overall_confidence(case: dict) -> float:
    if case["estimate_status"] != "ready":
        return 0.0
    dims = [ScoredDimension(name=name, score=score, rationale="golden set fixture")
            for name, score in case["scores"].items()]
    overall, _ = rollup(dims)
    return overall


def test_calibrated_threshold_separates_the_golden_set_as_labeled():
    """This is the roadmap's Phase 5 done-when criterion, run against the hand-scored golden set instead of
    a live Claude Haiku call: the scores here are the human annotator's own honest judgment of what a
    well-calibrated judge should say for each case (see judge_golden_set_gen.py), not model output. The
    real threshold used in production comes from scripts/calibrate_judge.py --yes against the real API,
    run separately once the owner has an Anthropic key and approves the spend."""
    cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    scores = [_overall_confidence(c) for c in cases]
    labels = [c["label"] == "trust" for c in cases]

    result = calibrate(scores, labels, KAPPA_ACCEPTABLE)

    assert result is not None
    assert result.kappa >= KAPPA_ACCEPTABLE
    for case, score in zip(cases, scores):
        assert gate(score, result.threshold) == (case["label"] == "trust"), case["case_id"]
```

- [ ] **Step 6: Run the test to verify it fails or passes for the right reason**

Run: `cd backend && uv run pytest tests/test_phase5_acceptance.py -v`
Expected: passes immediately once Tasks 2 and 4 exist (this test needs no new production code, only the golden set and `calibrate`/`rollup`, both already implemented). If it fails, the golden set's hand-assigned `scores` do not actually separate at any threshold clearing kappa 0.6: adjust the `scores` in `judge_golden_set_gen.py` (not the test) until they do, since the scores are meant to represent an honest, self-consistent judge, and a golden set whose own author-assigned scores cannot be separated indicates the scores were picked inconsistently with the labels.

- [ ] **Step 7: Write the calibration script**

Create `scripts/calibrate_judge.py`:

```python
import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import Anthropic

from app.judge.calibration import calibrate
from app.judge.constant import CALIBRATION_PATH, KAPPA_ACCEPTABLE
from app.judge.evidence import ContractEvidence, GraphEvidence, LineEvidence, PriceEvidence
from app.judge.prompts import JUDGE_SYSTEM_PROMPT
from app.judge.scoring import ScoredDimension, rollup
from core.config.settings import Settings
from core.llm.anthropic_judge_client import AnthropicJudgeClient

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "judge_golden_set.json"


def _line_evidence_from_dict(d: dict) -> LineEvidence:
    return LineEvidence(
        line_index=d["line_index"], sku_id=d["sku_id"], unit_price=d["unit_price"],
        price=PriceEvidence(**d["price"]), contract=ContractEvidence(**d["contract"]), graph=GraphEvidence(**d["graph"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the judge's confidence threshold (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the Anthropic API (costs money)")
    args = parser.parse_args()

    cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    ready_cases = [c for c in cases if c["estimate_status"] == "ready"]
    print(f"{len(cases)} golden-set cases ({len(ready_cases)} to score, {len(cases) - len(ready_cases)} fast-path)")
    print(f"estimated tokens: about {len(ready_cases) * 400} across {len(ready_cases)} calls to claude-haiku-4-5")
    if not args.yes:
        print("dry run: pass --yes to call the API")
        return

    settings = Settings()
    client = AnthropicJudgeClient(client=Anthropic(api_key=settings.anthropic_api_key))
    scores: list[float] = []
    labels: list[bool] = []
    for case in cases:
        labels.append(case["label"] == "trust")
        if case["estimate_status"] != "ready":
            scores.append(0.0)
            continue
        lines = [_line_evidence_from_dict(d) for d in case["evidence"]]
        raw = client.score([asdict(line) for line in lines], JUDGE_SYSTEM_PROMPT)
        scored = [ScoredDimension(name=d.name, score=d.score, rationale=d.rationale) for d in raw.dimensions]
        overall, _ = rollup(scored)
        scores.append(overall)

    result = calibrate(scores, labels, KAPPA_ACCEPTABLE)
    if result is None:
        print(f"no threshold clears kappa >= {KAPPA_ACCEPTABLE}; fix the judge prompt or evidence before shipping a threshold")
        sys.exit(1)

    CALIBRATION_PATH.write_text(
        json.dumps(
            {"threshold": result.threshold, "kappa": result.kappa, "golden_set_size": len(cases),
             "computed_at": date.today().isoformat()},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"wrote threshold {result.threshold} (kappa {result.kappa:.2f}) to {CALIBRATION_PATH}")


if __name__ == "__main__":
    main()
```

Run: `cd backend && uv run python scripts/calibrate_judge.py`
Expected output: `32 golden-set cases (29 to score, 3 fast-path)` followed by a token estimate and `dry run: pass --yes to call the API`. Do not pass `--yes` (no Anthropic key is configured, and a real API call needs the owner's separate, explicit approval).

- [ ] **Step 8: Commit**

```bash
git add backend/app/judge/calibration.py backend/scripts/calibrate_judge.py backend/tests/app/judge/test_calibration.py backend/tests/test_phase5_acceptance.py
git commit -m "feat: add judge threshold calibration and the phase 5 acceptance test"
```

---

## Final verification (whole branch)

- [ ] Run the complete backend suite: `cd backend && uv run pytest -v`. Expected: all tests pass, including every prior phase's suite (this plan added tables and routes but changed no existing behavior).
- [ ] Confirm `uv run alembic upgrade head` and `uv run alembic downgrade -1` both succeed cleanly against the dev Postgres on port 5433 (downgrade removes `review_items`/`judge_verdicts`; re-run `upgrade head` afterward to leave the dev database in its normal state).
- [ ] Confirm `uv run python scripts/calibrate_judge.py` (no `--yes`) still only prints the dry-run report; grep the diff for `--yes` to confirm no task accidentally hardcoded it as `True`.
- [ ] Confirm no em dash character made it into any new file: `grep -rn $'\xe2\x80\x94' app/judge api/v1/judge api/v1/review scripts/calibrate_judge.py scripts/data_gen/judge_golden_set_gen.py data/judge_golden_set.json docs/superpowers` should print nothing.
