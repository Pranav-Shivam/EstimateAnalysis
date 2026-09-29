import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import Anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.judge.calibration import calibrate, false_auto_send_rate
from app.judge.constant import CALIBRATION_PATH, FALSE_AUTO_SEND_CEILING, KAPPA_ACCEPTABLE
from app.judge.evidence import ContractEvidence, GraphEvidence, LineEvidence, PriceEvidence
from app.judge.models import EvalCaseRow
from app.judge.prompts import JUDGE_SYSTEM_PROMPT
from app.judge.scoring import ScoredDimension, rollup
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.llm.anthropic_judge_client import AnthropicJudgeClient

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "judge_golden_set.json"


def _line_evidence_from_dict(d: dict) -> LineEvidence:
    return LineEvidence(
        line_index=d["line_index"], sku_id=d["sku_id"], unit_price=d["unit_price"],
        price=PriceEvidence(**d["price"]), contract=ContractEvidence(**d["contract"]), graph=GraphEvidence(**d["graph"]),
    )


class MalformedEvalCase(Exception):
    pass


def load_eval_cases(session: Session) -> list[dict]:
    """Reviewer-resolved eval cases, whose evidence is every line's full evidence in the golden set's shape. A case
    that does not parse fails the run: scoring it on filled-in defaults would gate a release on made-up data."""
    cases = []
    for row in session.scalars(select(EvalCaseRow).order_by(EvalCaseRow.case_id)):
        try:
            for line in row.evidence:
                _line_evidence_from_dict(line)
        except (KeyError, TypeError) as exc:
            raise MalformedEvalCase(f"eval case {row.case_id} does not hold full line evidence: {exc!r}") from exc
        cases.append({
            "case_id": row.case_id, "label": row.label, "estimate_status": row.estimate_status,
            "evidence": row.evidence,
        })
    return cases


class NoAcceptableThreshold(Exception):
    pass


class CeilingBreached(Exception):
    def __init__(self, rate: float, wrong_case_ids: list[str]) -> None:
        super().__init__(f"false-auto-send rate {rate:.3f} exceeds ceiling {FALSE_AUTO_SEND_CEILING}")
        self.rate = rate
        self.wrong_case_ids = wrong_case_ids


def run_calibration(cases: list[dict], client: AnthropicJudgeClient, golden_set_size: int, eval_case_count: int) -> dict:
    """Scores every 'ready' case, calibrates a threshold, and checks the false-auto-send release gate. Returns
    the payload to write to CALIBRATION_PATH. Raises NoAcceptableThreshold or CeilingBreached instead of writing
    anything when either check fails, so a caller can never accidentally persist a threshold that failed its own
    gate."""
    fast_path_cases = [c for c in cases if c["estimate_status"] != "ready"]
    for case in fast_path_cases:
        assert case["label"] == "escalate", (
            f"fast-path case {case['case_id']} must be labeled escalate, got {case['label']!r}"
        )

    ready_cases = [c for c in cases if c["estimate_status"] == "ready"]
    scores: list[float] = []
    labels: list[bool] = []
    for case in ready_cases:
        labels.append(case["label"] == "trust")
        lines = [_line_evidence_from_dict(d) for d in case["evidence"]]
        raw = client.score([asdict(line) for line in lines], JUDGE_SYSTEM_PROMPT)
        scored = [ScoredDimension(name=d.name, score=d.score, rationale=d.rationale) for d in raw.dimensions]
        overall, _ = rollup(scored)
        scores.append(overall)

    result = calibrate(scores, labels, KAPPA_ACCEPTABLE)
    if result is None:
        raise NoAcceptableThreshold(f"no threshold clears kappa >= {KAPPA_ACCEPTABLE}")

    rate = false_auto_send_rate(result.pairs)
    if rate > FALSE_AUTO_SEND_CEILING:
        wrong_case_ids = [c["case_id"] for c, (trust, human) in zip(ready_cases, result.pairs) if trust and not human]
        raise CeilingBreached(rate, wrong_case_ids)

    return {
        "threshold": result.threshold, "kappa": result.kappa, "golden_set_size": golden_set_size,
        "eval_case_count": eval_case_count, "false_auto_send_rate": rate, "computed_at": date.today().isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the judge's confidence threshold (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the Anthropic API (costs money)")
    args = parser.parse_args()

    golden_cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    session = make_session_factory(make_engine(Settings().database_url))()
    try:
        eval_cases = load_eval_cases(session)
    finally:
        session.close()
    cases = golden_cases + eval_cases
    ready_count = len([c for c in cases if c["estimate_status"] == "ready"])
    print(f"{len(cases)} cases total ({len(golden_cases)} golden set, {len(eval_cases)} reviewer-corrected), "
          f"{ready_count} to score")
    print(f"estimated tokens: about {ready_count * 400} across {ready_count} calls to claude-haiku-4-5")
    if not args.yes:
        print("dry run: pass --yes to call the API")
        return

    settings = Settings()
    client = AnthropicJudgeClient(client=Anthropic(api_key=settings.anthropic_api_key))
    try:
        payload = run_calibration(cases, client, len(golden_cases), len(eval_cases))
    except NoAcceptableThreshold as exc:
        print(str(exc))
        sys.exit(1)
    except CeilingBreached as exc:
        print(f"release gate failed: {exc}")
        print("these cases would auto-send wrongly at this threshold:")
        for case_id in exc.wrong_case_ids:
            print(f"  {case_id}")
        sys.exit(1)

    CALIBRATION_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote threshold {payload['threshold']} (kappa {payload['kappa']:.2f}, "
        f"false-auto-send {payload['false_auto_send_rate']:.3f}) to {CALIBRATION_PATH}"
    )


if __name__ == "__main__":
    main()
