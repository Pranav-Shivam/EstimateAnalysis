from app.judge.calibration import calibrate, cohens_kappa, false_auto_send_rate


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


def test_false_auto_send_rate_counts_only_wrongly_trusted_cases():
    pairs = [(True, True), (True, False), (False, False), (False, True)]
    assert false_auto_send_rate(pairs) == 0.25


def test_false_auto_send_rate_is_zero_when_nothing_is_wrongly_trusted():
    assert false_auto_send_rate([(True, True), (False, False)]) == 0.0


def test_calibrate_result_carries_the_winning_pairs():
    result = calibrate(scores=[0.9, 0.9, 0.2], labels=[True, True, False], acceptable_kappa=0.6)
    assert result is not None
    assert len(result.pairs) == 3
