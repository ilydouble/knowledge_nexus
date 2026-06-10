from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MilvusChunk:
    chunk_id: str
    uri: str
    text: str
    created_by: str
    visibility: str
    vector: list[float]


class MilvusVectorStore:
    def __init__(self, host: str, port: int, dimensions: int = 64, collection_name: str = "nexus_chunks") -> None:
        self.host = host
        self.port = str(port)
        self.dimensions = dimensions
        self.collection_name = collection_name
        self.alias = f"nexus_{collection_name}"
        connections.connect(alias=self.alias, host=self.host, port=self.port, timeout=5)

    def ensure_collection(self, reset: bool = False) -> None:
        if reset and utility.has_collection(self.collection_name, using=self.alias, timeout=5):
            utility.drop_collection(self.collection_name, using=self.alias, timeout=10)
        if utility.has_collection(self.collection_name, using=self.alias, timeout=5):
            # Check whether the stored dimension matches the configured one.
            collection = Collection(self.collection_name, using=self.alias)
            try:
                for field in collection.schema.fields:
                    if field.name == "vector":
                        stored_dim = field.params.get("dim", self.dimensions)
                        if stored_dim != self.dimensions:
                            logger.warning(
                                "Milvus collection '%s' has dim=%d but embedding service uses dim=%d — "
                                "dropping and recreating collection to avoid shape mismatch.",
                                self.collection_name, stored_dim, self.dimensions,
                            )
                            utility.drop_collection(self.collection_name, using=self.alias, timeout=10)
                        break
            except Exception as exc:
                logger.warning("Could not inspect Milvus schema: %s", exc)
            # If collection still exists after the dimension check we're done.
            if utility.has_collection(self.collection_name, using=self.alias, timeout=5):
                return
        fields = [
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=512),
            FieldSchema(name="uri", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="created_by", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="visibility", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.dimensions),
        ]
        schema = CollectionSchema(fields=fields, description="Knowledge Nexus semantic chunks")
        collection = Collection(self.collection_name, schema=schema, using=self.alias)
        collection.create_index("vector", {"metric_type": "IP", "index_type": "FLAT", "params": {}}, timeout=10)
        # Milvus standalone may need a brief moment before DML channels are ready.
        time.sleep(1)

    def upsert_chunks(self, chunks: list[MilvusChunk]) -> None:
        if not chunks:
            return
        self.ensure_collection()
        collection = Collection(self.collection_name, using=self.alias)
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        expr = "chunk_id in [" + ", ".join(f'"{chunk_id}"' for chunk_id in chunk_ids) + "]"
        collection.delete(expr, timeout=10)
        collection.insert(
            [
                [chunk.chunk_id for chunk in chunks],
                [chunk.uri for chunk in chunks],
                [chunk.text for chunk in chunks],
                [chunk.created_by for chunk in chunks],
                [chunk.visibility for chunk in chunks],
                [chunk.vector for chunk in chunks],
            ]
        )
        # Avoid forcing flush in local standalone Milvus; growing segments are searchable after load.
        # Some existing dev instances report transient DML channel errors on flush.
        time.sleep(1)

    def search(self, vector: list[float], limit: int = 5) -> list[MilvusChunk]:
        collection = Collection(self.collection_name, using=self.alias)
        collection.load(timeout=10)
        results = collection.search(
            data=[vector],
            anns_field="vector",
            param={"metric_type": "IP", "params": {}},
            limit=limit,
            output_fields=["chunk_id", "uri", "text", "created_by", "visibility"],
            timeout=10,
        )
        chunks: list[MilvusChunk] = []
        for hit in results[0]:
            entity = hit.entity
            chunks.append(
                MilvusChunk(
                    chunk_id=entity.get("chunk_id"),
                    uri=entity.get("uri"),
                    text=entity.get("text"),
                    created_by=entity.get("created_by"),
                    visibility=entity.get("visibility"),
                    vector=[],
                )
            )
        return chunks

    def delete_chunks_by_uri(self, uri: str) -> None:
        """Delete all vector chunks belonging to *uri*."""
        if not utility.has_collection(self.collection_name, using=self.alias, timeout=5):
            return
        collection = Collection(self.collection_name, using=self.alias)
        expr = f'uri == "{uri}"'
        collection.delete(expr, timeout=10)

    def drop_collection(self) -> None:
        if utility.has_collection(self.collection_name, using=self.alias, timeout=5):
            utility.drop_collection(self.collection_name, using=self.alias, timeout=10)

    @staticmethod
    def _flush_with_retry(collection: Collection, attempts: int = 3) -> None:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                collection.flush(timeout=10)
                return
            except Exception as exc:  # Milvus can report transient DML channel readiness issues.
                last_error = exc
                if attempt == attempts - 1:
                    break
                time.sleep(1 + attempt)
        if last_error:
            raise last_error
