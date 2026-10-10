import hashlib
import logging
import math
import random
from typing import Protocol

from openai import OpenAI

from app.config import get_settings
from app.models import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, batch_size: int = 64) -> None:
        # The SDK retries rate limits and transient errors with exponential backoff.
        self.client = OpenAI(api_key=api_key, timeout=30.0, max_retries=3)
        self.model = model
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = self.client.embeddings.create(model=self.model, input=batch)
            logger.info("Embedded %d chunks (%d tokens)", len(batch), response.usage.total_tokens)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
        return vectors


class FakeEmbedder:
    """Deterministic offline vectors for tests and local dev. Not semantically meaningful."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        values = [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm for v in values]


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_provider == "fake":
        return FakeEmbedder()
    if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value():
        raise RuntimeError("OPENAI_API_KEY is not set (or set EMBEDDING_PROVIDER=fake)")
    return OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )
