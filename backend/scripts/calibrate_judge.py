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
