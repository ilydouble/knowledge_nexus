from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import uuid


def _read_dotenv(path: str = ".env") -> dict[str, str]:
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    cloudreve_base_url: str = "http://cloudreve:5212"
    cloudreve_token: str | None = None
    cloudreve_access_token: str | None = None
    cloudreve_refresh_token: str | None = None
    cloudreve_client_id: str = str(uuid.uuid5(uuid.NAMESPACE_URL, "knowledge-nexus-worker"))
    cloudreve_oauth_client_id: str | None = None
    cloudreve_oauth_client_secret: str | None = None
    cloudreve_oauth_redirect_uri: str = "http://localhost:8000/api/auth/cloudreve/callback"
    cloudreve_oauth_scope: str = "offline_access"
    cloudreve_token_store_path: str = "data/runtime/cloudreve_tokens.json"
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
    zhipu_api_key: str | None = None
    llm_provider: str = "zhipu"
    llm_model: str = "glm-4.7"
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    nexus_storage_backend: str = "memory"

    @classmethod
    def from_env(cls) -> "Settings":
        dotenv = _read_dotenv()

        def env(name: str, default: str | None = None) -> str | None:
            return os.getenv(name, dotenv.get(name, default))

        cloudreve_access_token = env("CLOUDREVE_ACCESS_TOKEN") or env("CLOUDREVE_TOKEN") or None
        cloudreve_refresh_token = env("CLOUDREVE_REFRESH_TOKEN") or None

        return cls(
            cloudreve_base_url=env("CLOUDREVE_BASE_URL", cls.cloudreve_base_url) or cls.cloudreve_base_url,
            cloudreve_token=cloudreve_access_token,
            cloudreve_access_token=cloudreve_access_token,
            cloudreve_refresh_token=cloudreve_refresh_token,
            cloudreve_client_id=env("CLOUDREVE_CLIENT_ID", cls.cloudreve_client_id) or cls.cloudreve_client_id,
            cloudreve_oauth_client_id=env("CLOUDREVE_OAUTH_CLIENT_ID") or None,
            cloudreve_oauth_client_secret=env("CLOUDREVE_OAUTH_CLIENT_SECRET") or None,
            cloudreve_oauth_redirect_uri=env("CLOUDREVE_OAUTH_REDIRECT_URI", cls.cloudreve_oauth_redirect_uri)
            or cls.cloudreve_oauth_redirect_uri,
            cloudreve_oauth_scope=env("CLOUDREVE_OAUTH_SCOPE", cls.cloudreve_oauth_scope) or cls.cloudreve_oauth_scope,
            cloudreve_token_store_path=env("CLOUDREVE_TOKEN_STORE_PATH", cls.cloudreve_token_store_path)
            or cls.cloudreve_token_store_path,
            database_url=env("DATABASE_URL", cls.database_url) or cls.database_url,
            redis_url=env("REDIS_URL", cls.redis_url) or cls.redis_url,
            neo4j_uri=env("NEO4J_URI", cls.neo4j_uri) or cls.neo4j_uri,
            neo4j_user=env("NEO4J_USER", cls.neo4j_user) or cls.neo4j_user,
            neo4j_password=env("NEO4J_PASSWORD", cls.neo4j_password) or cls.neo4j_password,
            vector_backend=env("VECTOR_BACKEND", cls.vector_backend) or cls.vector_backend,
            milvus_host=env("MILVUS_HOST", cls.milvus_host) or cls.milvus_host,
            milvus_port=int(env("MILVUS_PORT", str(cls.milvus_port)) or str(cls.milvus_port)),
            minio_endpoint=env("MINIO_ENDPOINT", cls.minio_endpoint) or cls.minio_endpoint,
            minio_access_key=env("MINIO_ACCESS_KEY", cls.minio_access_key) or cls.minio_access_key,
            minio_secret_key=env("MINIO_SECRET_KEY", cls.minio_secret_key) or cls.minio_secret_key,
            openai_api_key=env("OPENAI_API_KEY") or None,
            zhipu_api_key=env("ZHIPU_API_KEY") or env("BIGMODEL_API_KEY") or None,
            llm_provider=env("LLM_PROVIDER", cls.llm_provider) or cls.llm_provider,
            llm_model=env("LLM_MODEL", cls.llm_model) or cls.llm_model,
            llm_base_url=env("LLM_BASE_URL", cls.llm_base_url) or cls.llm_base_url,
            nexus_storage_backend=env("NEXUS_STORAGE_BACKEND", cls.nexus_storage_backend) or cls.nexus_storage_backend,
        )
