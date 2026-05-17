import pytest

from nexus.services.embedding import BigModelEmbeddingService, DeterministicEmbeddingService


def test_deterministic_embedding_is_stable_and_normalized():
    service = DeterministicEmbeddingService(dimensions=16)

    first = service.embed("infrared sensor thermal calibration")
    second = service.embed("infrared sensor thermal calibration")

    assert first == second
    assert len(first) == 16
    assert abs(sum(value * value for value in first) - 1.0) < 0.000001


def test_deterministic_embedding_gives_related_texts_higher_similarity():
    service = DeterministicEmbeddingService(dimensions=32)

    query = service.embed("infrared sensor calibration")
    related = service.embed("thermal infrared sensor notes")
    unrelated = service.embed("quarterly finance payroll policy")

    assert service.cosine_similarity(query, related) > service.cosine_similarity(query, unrelated)


# ---------------------------------------------------------------------------
# BigModelEmbeddingService tests (fake HTTP client)
# ---------------------------------------------------------------------------

class FakeBigModelResponse:
    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "data": [
                {"index": i, "embedding": v}
                for i, v in enumerate(self._vectors)
            ]
        }


class FakeBigModelHttpClient:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict) -> FakeBigModelResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        # Return vectors for however many texts were sent, cycling if needed
        n = len(json["input"])
        return FakeBigModelResponse(self.vectors[:n])


def _make_service(vectors: list[list[float]], dimensions: int = 4) -> tuple[BigModelEmbeddingService, FakeBigModelHttpClient]:
    client = FakeBigModelHttpClient(vectors)
    service = BigModelEmbeddingService(
        api_key="test-key",
        model="embedding-3",
        dimensions=dimensions,
        http_client=client,
    )
    return service, client


def test_bigmodel_embedding_calls_api_and_returns_vector():
    vec = [0.1, 0.2, 0.3, 0.4]
    service, client = _make_service([vec])

    result = service.embed("hello world")

    assert result == vec
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == BigModelEmbeddingService.DEFAULT_BASE_URL
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["model"] == "embedding-3"
    assert call["json"]["input"] == ["hello world"]
    assert call["json"]["dimensions"] == 4


def test_bigmodel_embed_batch_returns_vectors_in_order():
    vecs = [[float(i)] * 4 for i in range(3)]
    service, client = _make_service(vecs)

    results = service.embed_batch(["a", "b", "c"])

    assert results == vecs
    assert len(client.calls) == 1  # all in one batch


def test_bigmodel_embed_batch_splits_into_max_batch_size():
    """If more texts than MAX_BATCH_SIZE are supplied, multiple POST calls are made."""
    max_b = BigModelEmbeddingService.MAX_BATCH_SIZE
    n = max_b + 1
    vecs = [[float(i), 0.0, 0.0, 0.0] for i in range(n)]

    # Client returns first max_b vectors for each call
    client = FakeBigModelHttpClient(vecs)
    service = BigModelEmbeddingService(
        api_key="test-key",
        dimensions=4,
        http_client=client,
    )

    results = service.embed_batch([f"text_{i}" for i in range(n)])

    assert len(results) == n
    assert len(client.calls) == 2  # split into two POST requests
    assert len(client.calls[0]["json"]["input"]) == max_b
    assert len(client.calls[1]["json"]["input"]) == 1


def test_bigmodel_embed_batch_empty_returns_empty():
    service, _ = _make_service([])
    assert service.embed_batch([]) == []


def test_bigmodel_service_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        BigModelEmbeddingService(api_key="")

