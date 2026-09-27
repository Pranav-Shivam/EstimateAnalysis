from app.dedupe.fingerprints import classify, is_strict_superset, jaccard


def test_jaccard_identical_sets_is_one():
    assert jaccard({"A", "B"}, {"A", "B"}) == 1.0


def test_jaccard_disjoint_sets_is_zero():
    assert jaccard({"A"}, {"B"}) == 0.0


def test_jaccard_both_empty_is_zero():
    assert jaccard(set(), set()) == 0.0


def test_is_strict_superset_true_case():
    assert is_strict_superset({"A", "B", "C"}, {"A", "B"}) is True


def test_is_strict_superset_false_when_equal():
    assert is_strict_superset({"A", "B"}, {"A", "B"}) is False


def test_is_strict_superset_false_when_smaller_is_empty():
    # An empty set is never treated as a meaningful subset of anything --
    # an unresolved request must never be read as a "revision" of every other request.
    assert is_strict_superset({"A", "B"}, set()) is False


def test_classify_identical_sets_is_duplicate():
    verdict, score, signals = classify({"A", "B"}, {"A", "B"})
    assert verdict == "DUPLICATE_OF"
    assert score == 1.0
    assert "identical_sku_set" in signals


def test_classify_superset_above_floor_is_revision():
    verdict, score, signals = classify({"A", "B"}, {"A", "B", "C"})
    assert verdict == "REVISION_OF"
    assert score == 2 / 3
    assert "superset_relation" in signals


def test_classify_superset_below_floor_is_distinct():
    # sharing one SKU out of five is not a "revision" of a much larger, unrelated order
    verdict, score, signals = classify({"A"}, {"A", "B", "C", "D", "E"})
    assert verdict == "DISTINCT"


def test_classify_disjoint_sets_is_distinct():
    verdict, score, signals = classify({"A"}, {"B"})
    assert verdict == "DISTINCT"
    assert score == 0.0


def test_classify_two_empty_sets_is_distinct_not_duplicate():
    # Two unresolved requests must not be flagged as duplicates of each other.
    verdict, score, signals = classify(set(), set())
    assert verdict == "DISTINCT"
