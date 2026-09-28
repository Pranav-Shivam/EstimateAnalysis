from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.llm.openai_embedding_client import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EmbeddingError, OpenAIEmbeddingClient,
)


def _vector(value):
    return [value] * EMBEDDING_DIMENSIONS


def _openai(items):
    create = MagicMock(return_value=SimpleNamespace(data=items))
    return SimpleNamespace(embeddings=SimpleNamespace(create=create)), create


def _item(index, value):
    return SimpleNamespace(index=index, embedding=_vector(value))


def test_embed_returns_vectors_in_input_order_even_if_the_api_shuffles_them():
    openai, create = _openai([_item(1, 0.2), _item(0, 0.1)])

    vectors = OpenAIEmbeddingClient(client=openai).embed(["first", "second"])

    assert vectors[0][0] == 0.1 and vectors[1][0] == 0.2
    assert create.call_args.kwargs == {"model": EMBEDDING_MODEL, "input": ["first", "second"]}


def test_embedding_nothing_makes_no_call():
    openai, create = _openai([])

    assert OpenAIEmbeddingClient(client=openai).embed([]) == []
    create.assert_not_called()


def test_a_count_mismatch_is_an_error():
    openai, _ = _openai([_item(0, 0.1)])

    with pytest.raises(EmbeddingError, match="1 embeddings for 2 inputs"):
        OpenAIEmbeddingClient(client=openai).embed(["a", "b"])


def test_missing_data_is_an_error():
    openai = SimpleNamespace(embeddings=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(data=None))))

    with pytest.raises(EmbeddingError):
        OpenAIEmbeddingClient(client=openai).embed(["a"])


def test_a_wrong_dimension_is_an_error():
    bad = SimpleNamespace(index=0, embedding=[0.1, 0.2])
    openai, _ = _openai([bad])

    with pytest.raises(EmbeddingError, match="dimension"):
        OpenAIEmbeddingClient(client=openai).embed(["a"])


def test_an_api_failure_is_wrapped():
    openai, create = _openai([])
    create.side_effect = RuntimeError("boom")

    with pytest.raises(EmbeddingError, match="boom"):
        OpenAIEmbeddingClient(client=openai).embed(["a"])
