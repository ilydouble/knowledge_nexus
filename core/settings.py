from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


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
    cloudreve_oauth_client_id: str | None = None
    cloudreve_oauth_client_secret: str | None = None
    cloudreve_oauth_redirect_uri: str = "http://localhost:8000/api/auth/cloudreve/callback"
    cloudreve_oauth_scope: str = "openid profile offline_access Files.Read"
    cloudreve_token_store_path: str = "data/runtime/cloudreve_tokens.json"
    cloudreve_oauth_config_path: str = "data/runtime/cloudreve_oauth_config.json"
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
    minio_bucket: str = "knowledge-nexus"
    # Local directory used as the artifact fallback when MinIO is unavailable.
    # Full parsed text is written here so parsed_text_key is always a local://
    # URI (never a cloudreve:// provenance pointer).
    artifact_local_dir: str = "data/artifacts"
    openai_api_key: str | None = None
    zhipu_api_key: str | None = None
    llm_provider: str = "zhipu"
    llm_model: str = "glm-4.7"
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    # Number of parallel LLM requests during map-reduce extraction.
    # Set to 1 to disable concurrency and avoid rate-limit errors.
    llm_max_workers: int = 1
    # Single-pass context limit (chars).  Documents at or below this size are
    # sent to the LLM in one call.  Defaults to 100 000 chars (~50 k tokens)
    # which is well within the 128 k-token context of modern models such as
    # GLM-4-Flash / GLM-4.7.  Set LLM_SINGLE_PASS_LIMIT to tune per deployment.
    llm_single_pass_limit: int = 100_000
    # Documents longer than this (chars) switch to the map-reduce path.
    # Keep in sync with llm_single_pass_limit so there is no gap between the
    # two thresholds.
    llm_map_reduce_threshold: int = 100_000
    # Embedding settings (BigModel embedding-3)
    embedding_model: str = "embedding-3"
    embedding_dimensions: int = 2048
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4/embeddings"
    nexus_storage_backend: str = "memory"
    hyper_extract_runtime_enabled: bool = False
    hyper_extract_runtime_max_templates: int = 1

    @classmethod
    def from_env(cls) -> "Settings":
        dotenv = _read_dotenv()

        def env(name: str, default: str | None = None) -> str | None:
            return os.getenv(name, dotenv.get(name, default))

        def env_bool(name: str, default: bool = False) -> bool:
            value = env(name, str(default).lower())
            return str(value).lower() in {"1", "true", "yes", "on"}

        cloudreve_access_token = env("CLOUDREVE_ACCESS_TOKEN") or env("CLOUDREVE_TOKEN") or None
        cloudreve_refresh_token = env("CLOUDREVE_REFRESH_TOKEN") or None

        return cls(
            cloudreve_base_url=env("CLOUDREVE_BASE_URL", cls.cloudreve_base_url) or cls.cloudreve_base_url,
            cloudreve_token=cloudreve_access_token,
            cloudreve_access_token=cloudreve_access_token,
            cloudreve_refresh_token=cloudreve_refresh_token,
            cloudreve_oauth_client_id=env("CLOUDREVE_OAUTH_CLIENT_ID") or None,
            cloudreve_oauth_client_secret=env("CLOUDREVE_OAUTH_CLIENT_SECRET") or None,
            cloudreve_oauth_redirect_uri=env("CLOUDREVE_OAUTH_REDIRECT_URI", cls.cloudreve_oauth_redirect_uri)
            or cls.cloudreve_oauth_redirect_uri,
            cloudreve_oauth_scope=env("CLOUDREVE_OAUTH_SCOPE", cls.cloudreve_oauth_scope) or cls.cloudreve_oauth_scope,
            cloudreve_token_store_path=env("CLOUDREVE_TOKEN_STORE_PATH", cls.cloudreve_token_store_path)
            or cls.cloudreve_token_store_path,
            cloudreve_oauth_config_path=env("CLOUDREVE_OAUTH_CONFIG_PATH", cls.cloudreve_oauth_config_path)
            or cls.cloudreve_oauth_config_path,
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
            minio_bucket=env("MINIO_BUCKET", cls.minio_bucket) or cls.minio_bucket,
            artifact_local_dir=env("ARTIFACT_LOCAL_DIR", cls.artifact_local_dir) or cls.artifact_local_dir,
            openai_api_key=env("OPENAI_API_KEY") or None,
            zhipu_api_key=env("ZHIPU_API_KEY") or env("BIGMODEL_API_KEY") or None,
            llm_provider=env("LLM_PROVIDER", cls.llm_provider) or cls.llm_provider,
            llm_model=env("LLM_MODEL", cls.llm_model) or cls.llm_model,
            llm_base_url=env("LLM_BASE_URL", cls.llm_base_url) or cls.llm_base_url,
            llm_max_workers=int(env("LLM_MAX_WORKERS", str(cls.llm_max_workers)) or str(cls.llm_max_workers)),
            llm_single_pass_limit=int(env("LLM_SINGLE_PASS_LIMIT", str(cls.llm_single_pass_limit)) or str(cls.llm_single_pass_limit)),
            llm_map_reduce_threshold=int(env("LLM_MAP_REDUCE_THRESHOLD", str(cls.llm_map_reduce_threshold)) or str(cls.llm_map_reduce_threshold)),
            embedding_model=env("EMBEDDING_MODEL", cls.embedding_model) or cls.embedding_model,
            embedding_dimensions=int(env("EMBEDDING_DIMENSIONS", str(cls.embedding_dimensions)) or str(cls.embedding_dimensions)),
            embedding_base_url=env("EMBEDDING_BASE_URL", cls.embedding_base_url) or cls.embedding_base_url,
            nexus_storage_backend=env("NEXUS_STORAGE_BACKEND", cls.nexus_storage_backend) or cls.nexus_storage_backend,
            hyper_extract_runtime_enabled=env_bool(
                "HYPER_EXTRACT_RUNTIME_ENABLED",
                cls.hyper_extract_runtime_enabled,
            ),
            hyper_extract_runtime_max_templates=int(
                env(
                    "HYPER_EXTRACT_RUNTIME_MAX_TEMPLATES",
                    str(cls.hyper_extract_runtime_max_templates),
                )
                or str(cls.hyper_extract_runtime_max_templates)
            ),
        )
