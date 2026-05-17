# Knowledge Nexus 本地开发指南

## 当前推荐模式

本项目当前推荐复用已有的 `kg-*` Docker 基础设施，而不是为 Knowledge Nexus 重复安装或启动数据库组件。

已发现并复用的本地服务：

| 服务 | 容器 | Host 访问 | Docker network 访问 |
| :--- | :--- | :--- | :--- |
| PostgreSQL / pgvector | `kg-postgres` | `localhost:5433` | `kg-postgres:5432` |
| Neo4j | `kg-neo4j` | `localhost:7687` | `kg-neo4j:7687` |
| Redis | `kg-redis` | `localhost:6380` | `kg-redis:6379` |
| Milvus | `kg-milvus` | `localhost:19530` | `kg-milvus:19530` |
| MinIO | `kg-minio` | `localhost:9000` / `9001` | `kg-minio:9000` |

这些容器都在外部 Docker network：`kg-network`。

## Host 开发

Host 开发适合直接运行 Python 和 Vite：

```bash
conda activate nexus
python --version
cp .env.local.example .env
uvicorn apps.api.main:app --reload
```

另开一个终端运行 Web：

```bash
cd apps/web
npm run dev
```

访问入口：

- Nexus API: http://localhost:8000
- Nexus Web Console: http://localhost:5173
- MinIO Console: http://localhost:9001

MinIO 本地开发凭据：

- User: `minioadmin`
- Password: `minioadmin`

注意：这些凭据只允许用于本地开发。

## Docker Sidecar 开发

Docker sidecar 模式只启动 Nexus 自己的服务，不重复启动 `kg-*` 基础设施：

```bash
cp .env.docker.example .env
docker compose -f infrastructure/docker/docker-compose.yml up --build
```

默认启动：

- `nexus-api`
- `nexus-worker`
- `nexus-web`

默认 Compose 会接入外部 `kg-network`。如果本机没有 `kg-network`，先启动已有知识图谱基础设施，或使用 `infrastructure/docker/docker-compose.full.yml` 作为新机器全量参考。

## 测试

日常测试不依赖外部服务：

```bash
python3 -m pytest
npm run build --prefix apps/web
docker compose -f infrastructure/docker/docker-compose.yml config
```

外部组件集成测试需要显式开启：

```bash
RUN_INTEGRATION=1 DATABASE_URL=postgresql://admin:admin123@localhost:5433/smart_building python3 -m pytest tests/integration/test_postgres_repository.py
RUN_INTEGRATION=1 NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=admin123 python3 -m pytest tests/integration/test_neo4j_store.py
RUN_INTEGRATION=1 MILVUS_HOST=localhost MILVUS_PORT=19530 python3 -m pytest tests/integration/test_milvus_store.py
```

当前状态：

- Postgres 集成测试已通过。
- Neo4j 集成测试已通过。
- Milvus adapter 已实现，但当前 `kg-milvus` 实例在 collection 写入/加载时返回 DML channel/loading 错误，真实 Milvus 集成测试暂未通过。

## 依赖隔离建议

当前推荐使用已配置好的 Conda 环境：

```bash
conda activate nexus
python --version
python -m pytest
```

推荐 Python 版本为 3.11.x。原因是当前复用的 Milvus 服务为 `milvusdb/milvus:v2.3.3`，项目需要 `pymilvus>=2.3,<2.4`。这个旧版 SDK 还依赖：

- `setuptools<81`，用于保留 `pkg_resources`。
- `marshmallow<4`，用于兼容 `environs<=9.5.0`。

这些 pin 已写入 `pyproject.toml`。不要在全局 Python 环境里反复安装这些依赖，避免影响其他项目。

如果需要重建 `nexus` 环境：

```bash
conda install -n nexus -y python=3.11 pip
conda run -n nexus python -m pip install --no-build-isolation -e ".[dev]"
```
