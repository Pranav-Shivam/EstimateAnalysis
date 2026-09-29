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
