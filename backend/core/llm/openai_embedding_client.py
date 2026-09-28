from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


class EmbeddingError(Exception):
    pass


class OpenAIEmbeddingClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding call failed: {exc}") from exc

        items = sorted(response.data or [], key=lambda item: item.index)
        if len(items) != len(texts):
            raise EmbeddingError(f"OpenAI returned {len(items)} embeddings for {len(texts)} inputs")
        vectors = [list(item.embedding) for item in items]
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise EmbeddingError(f"OpenAI returned a vector of dimension {len(vector)}, expected {EMBEDDING_DIMENSIONS}")
        return vectors
