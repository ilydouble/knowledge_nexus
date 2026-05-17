import os

import pytest

from nexus.services.embedding import DeterministicEmbeddingService
from nexus.settings import Settings
from nexus.vector.milvus_store import MilvusChunk, MilvusVectorStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run Milvus integration tests")


def test_milvus_store_indexes_and_searches_similar_chunks():
    settings = Settings.from_env()
    embedding = DeterministicEmbeddingService(dimensions=64)
    store = MilvusVectorStore(host=settings.milvus_host, port=settings.milvus_port, dimensions=64, collection_name="nexus_chunks_test")
    store.ensure_collection(reset=True)

    infrared_chunk = MilvusChunk(
        chunk_id="integration-chunk-1",
        uri="cloudreve://integration/infrared.md",
        text="infrared sensor thermal calibration notes",
        created_by="integration-user",
        visibility="private",
        vector=embedding.embed("infrared sensor thermal calibration notes"),
    )
    payroll_chunk = MilvusChunk(
        chunk_id="integration-chunk-2",
        uri="cloudreve://integration/payroll.md",
        text="quarterly finance payroll policy",
        created_by="integration-user",
        visibility="private",
        vector=embedding.embed("quarterly finance payroll policy"),
    )

    store.upsert_chunks([infrared_chunk, payroll_chunk])
    results = store.search(embedding.embed("thermal infrared sensor"), limit=1)

    assert results[0].chunk_id == infrared_chunk.chunk_id
    assert results[0].uri == infrared_chunk.uri
    assert "infrared" in results[0].text

    store.drop_collection()

