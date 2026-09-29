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
