from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    cloudreve_base_url: str = "http://cloudreve:5212"
    cloudreve_token: str | None = None
    cloudreve_client_id: str = "knowledge-nexus-worker"
    database_url: str = "postgresql://admin:admin123@localhost:5433/smart_building"
    redis_url: str = "redis://localhost:6380/0"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "admin123"
    vector_backend: str = "milvus"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    openai_api_key: str | None = None
    nexus_storage_backend: str = "memory"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            cloudreve_base_url=os.getenv("CLOUDREVE_BASE_URL", cls.cloudreve_base_url),
            cloudreve_token=os.getenv("CLOUDREVE_TOKEN") or None,
            cloudreve_client_id=os.getenv("CLOUDREVE_CLIENT_ID", cls.cloudreve_client_id),
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            redis_url=os.getenv("REDIS_URL", cls.redis_url),
            neo4j_uri=os.getenv("NEO4J_URI", cls.neo4j_uri),
            neo4j_user=os.getenv("NEO4J_USER", cls.neo4j_user),
            neo4j_password=os.getenv("NEO4J_PASSWORD", cls.neo4j_password),
            vector_backend=os.getenv("VECTOR_BACKEND", cls.vector_backend),
            milvus_host=os.getenv("MILVUS_HOST", cls.milvus_host),
            milvus_port=int(os.getenv("MILVUS_PORT", str(cls.milvus_port))),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", cls.minio_endpoint),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", cls.minio_access_key),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", cls.minio_secret_key),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            nexus_storage_backend=os.getenv("NEXUS_STORAGE_BACKEND", cls.nexus_storage_backend),
        )
