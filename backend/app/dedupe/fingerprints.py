import re

STOPWORDS = {"the", "a", "an", "and", "or", "to", "for", "of", "on", "in", "is", "we", "i", "please", "thanks", "hi", "hello"}


def normalize_style_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for line in text.lower().splitlines():
        for word in re.findall(r"[a-z0-9]+", line):
            if word not in STOPWORDS:
                tokens.add(word)
    return tokens
