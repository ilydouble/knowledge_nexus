from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BigModel embedding-3 service (real vectors)
# ---------------------------------------------------------------------------

class BigModelEmbeddingService:
    """Embed text using the BigModel ``embedding-3`` model.

    API reference: https://docs.bigmodel.cn/cn/guide/models/embedding/embedding-3

    Supports:
    * Variable output dimensions (2048 / 1024 / 512 / 256)
    * Batch requests (max 64 texts per call)
    * Automatic retry on transient HTTP errors is left to the caller.
    """

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
    DEFAULT_MODEL = "embedding-3"
    DEFAULT_DIMENSIONS = 2048
    MAX_BATCH_SIZE = 64  # BigModel API hard limit

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        http_client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for BigModelEmbeddingService")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.base_url = base_url
        self.timeout = timeout
        self._http_client = http_client or httpx.Client(timeout=timeout)

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for a single *text* string."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of *texts*.

        Automatically splits into batches of at most ``MAX_BATCH_SIZE`` and
        concatenates the results in the original order.
        """
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[i : i + self.MAX_BATCH_SIZE]
            results.extend(self._call_api(batch))
        return results

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call the BigModel embeddings endpoint for one batch."""
        response = self._http_client.post(
            self.base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": self.model,
                "input": texts,
                "dimensions": self.dimensions,
            },
        )
        response.raise_for_status()
        payload = response.json()
        # Sort by index so order matches the input list
        items = sorted(payload["data"], key=lambda x: x["index"])
        vectors = [item["embedding"] for item in items]
        logger.debug(
            "BigModel embed: %d texts → %d-dim vectors", len(texts), self.dimensions
        )
        return vectors


# ---------------------------------------------------------------------------
# Deterministic (hash-based) embedding — used as fallback / in tests
# ---------------------------------------------------------------------------

class DeterministicEmbeddingService:
    def __init__(self, dimensions: int = 64) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts (mirrors BigModelEmbeddingService.embed_batch)."""
        return [self.embed(t) for t in texts]

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[A-Za-z0-9_-]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return self._normalize(vector)

    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

