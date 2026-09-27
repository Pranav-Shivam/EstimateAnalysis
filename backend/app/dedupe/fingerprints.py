import re

STOPWORDS = {"the", "a", "an", "and", "or", "to", "for", "of", "on", "in", "is", "we", "i", "please", "thanks", "hi", "hello"}


def normalize_style_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for line in text.lower().splitlines():
        for word in re.findall(r"[a-z0-9]+", line):
            if word not in STOPWORDS:
                tokens.add(word)
    return tokens


CONTENT_SUPERSET_FLOOR = 0.4


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def is_strict_superset(bigger: set[str], smaller: set[str]) -> bool:
    return bool(smaller) and smaller < bigger


def classify(sku_ids_a: set[str], sku_ids_b: set[str]) -> tuple[str, float, list[str]]:
    score = jaccard(sku_ids_a, sku_ids_b)

    if score == 1.0 and sku_ids_a:
        return "DUPLICATE_OF", score, ["identical_sku_set"]

    if is_strict_superset(sku_ids_a, sku_ids_b) or is_strict_superset(sku_ids_b, sku_ids_a):
        if score >= CONTENT_SUPERSET_FLOOR:
            return "REVISION_OF", score, ["superset_relation"]

    return "DISTINCT", score, []
