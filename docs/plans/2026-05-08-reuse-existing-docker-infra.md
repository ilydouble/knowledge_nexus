# Reuse Existing Docker Infrastructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reconfigure Knowledge Nexus to reuse the already-running `kg-*` Docker services instead of reinstalling or starting duplicate Postgres, Redis, Neo4j, Milvus, and MinIO containers.

**Architecture:** Keep Cloudreve optional and keep Nexus as a sidecar. Local Python development connects to existing services through host ports; Dockerized Nexus services join the existing `kg-network` and connect by container DNS names. The vector backend becomes Milvus-first because Milvus is already running.

**Tech Stack:** Python FastAPI, PostgreSQL/pgvector, Neo4j, Redis, Milvus, MinIO, Docker Compose, pytest.

---

## Discovered Local Infrastructure

- `kg-postgres`: `ankane/pgvector:latest`, network `kg-network`, host port `5433`, db `smart_building`, user `admin`, password `admin123`.
- `kg-neo4j`: `neo4j:5-community`, network `kg-network`, host ports `7474` and `7687`, auth `neo4j/admin123`, APOC enabled.
- `kg-redis`: `redis:7-alpine`, network `kg-network`, host port `6380`.
- `kg-milvus`: `milvusdb/milvus:v2.3.3`, network `kg-network`, host ports `19530` and `9091`.
- `kg-minio`: MinIO, network `kg-network`, host ports `9000` and `9001`, console currently open at `http://localhost:9001/login`, root user `minioadmin`, password `minioadmin`.
- `kg-network`: existing bridge network shared by all `kg-*` services.

## Task 1: Split Local Config From Container Config

**Files:**
- Modify: `.env.example`
- Create: `.env.local.example`
- Create: `.env.docker.example`

**Steps:**
1. Write `.env.local.example` for running `uvicorn` directly on the host:
   - `DATABASE_URL=postgresql://admin:admin123@localhost:5433/smart_building`
   - `REDIS_URL=redis://localhost:6380/0`
   - `NEO4J_URI=bolt://localhost:7687`
   - `NEO4J_USER=neo4j`
   - `NEO4J_PASSWORD=admin123`
   - `MILVUS_HOST=localhost`
   - `MILVUS_PORT=19530`
   - `MINIO_ENDPOINT=http://localhost:9000`
   - `MINIO_ACCESS_KEY=minioadmin`
   - `MINIO_SECRET_KEY=minioadmin`
2. Write `.env.docker.example` for running Nexus in Docker on `kg-network`:
   - `DATABASE_URL=postgresql://admin:admin123@kg-postgres:5432/smart_building`
   - `REDIS_URL=redis://kg-redis:6379/0`
   - `NEO4J_URI=bolt://kg-neo4j:7687`
   - `MILVUS_HOST=kg-milvus`
   - `MILVUS_PORT=19530`
   - `MINIO_ENDPOINT=http://kg-minio:9000`
3. Update `.env.example` to explain which file to copy for each mode.
4. Run `python3 -m pytest`.
5. Expected: all existing tests pass.

## Task 2: Replace Full Compose With Sidecar Compose

**Files:**
- Modify: `infrastructure/docker/docker-compose.yml`
- Create: `infrastructure/docker/docker-compose.full.yml`

**Steps:**
1. Change default `docker-compose.yml` to start only:
   - `nexus-api`
   - `nexus-worker`
   - `nexus-web`
2. Attach all three services to external network `kg-network`.
3. Remove default `postgres`, `redis`, `neo4j`, `qdrant`, and `minio` services from default compose.
4. Replace `QDRANT_URL` with Milvus settings.
5. Keep Cloudreve optional:
   - Do not start Cloudreve by default.
   - Keep `CLOUDREVE_BASE_URL=http://host.docker.internal:5212` as the default placeholder unless a Cloudreve container is later added.
6. Move the old all-in-one stack to `docker-compose.full.yml` for clean machines.
7. Run `docker compose -f infrastructure/docker/docker-compose.yml config`.
8. Expected: compose validates and references `kg-network` as external.

## Task 3: Add Settings Object

**Files:**
- Create: `nexus/settings.py`
- Modify: `nexus/cloudreve/client.py`
- Test: `tests/unit/test_settings.py`

**Steps:**
1. Write failing tests for:
   - local env loads `DATABASE_URL`.
   - missing optional AI key does not crash.
   - default vector backend is `milvus`.
2. Implement `Settings` using `pydantic-settings` or a tiny env reader if avoiding a new dependency.
3. Use `Settings` in `CloudreveClient` instead of directly reading `os.getenv`.
4. Run `python3 -m pytest tests/unit/test_settings.py tests/unit/test_cloudreve_client.py`.
5. Expected: tests pass.

## Task 4: Introduce Repository Interfaces

**Files:**
- Modify: `nexus/repository.py`
- Create: `nexus/repositories/base.py`
- Create: `nexus/repositories/memory.py`
- Test: `tests/unit/test_repository_contract.py`

**Steps:**
1. Extract a repository protocol for jobs, documents, links, and graph reads.
2. Move current `InMemoryRepository` to `nexus/repositories/memory.py`.
3. Keep `nexus/repository.py` as a compatibility re-export for existing tests.
4. Write a contract test that runs against `InMemoryRepository`.
5. Run `python3 -m pytest`.
6. Expected: existing API behavior unchanged.

## Task 5: Add PostgreSQL Persistence For Jobs And Documents

**Files:**
- Create: `nexus/repositories/postgres.py`
- Create: `nexus/db/schema.sql`
- Create: `scripts/init_postgres.py`
- Test: `tests/integration/test_postgres_repository.py`

**Steps:**
1. Add schema tables:
   - `ingestion_jobs`
   - `semantic_documents`
   - `semantic_chunks`
   - `knowledge_links`
2. Include `tenant_id` and `created_by` columns even if MVP uses defaults.
3. Use plain SQL first; avoid ORM until schema stabilizes.
4. Add integration test guarded by `RUN_INTEGRATION=1` so unit tests remain fast.
5. Test creates job, document, chunks, and link, then reads them back.
6. Run `RUN_INTEGRATION=1 python3 -m pytest tests/integration/test_postgres_repository.py`.
7. Expected: data persists in `kg-postgres`.

## Task 6: Add Neo4j Graph Adapter

**Files:**
- Create: `nexus/graph/neo4j_store.py`
- Test: `tests/integration/test_neo4j_store.py`

**Steps:**
1. Add node upsert for file nodes with `uri`, `label`, `summary`, `layer`.
2. Add edge upsert with required properties:
   - `layer`
   - `owner_scope`
   - `source_file_uri`
   - `visibility`
3. Add neighborhood query by URI, layers, and depth.
4. Keep permission filtering outside Neo4j adapter.
5. Run integration test against `kg-neo4j`.
6. Expected: L3 link can be written and read back as graph edge.

## Task 7: Add Milvus Vector Adapter

**Files:**
- Create: `nexus/vector/milvus_store.py`
- Create: `nexus/services/embedding.py`
- Test: `tests/integration/test_milvus_store.py`

**Steps:**
1. Add deterministic local embedding fallback for tests, such as hashing tokens into a fixed-size vector.
2. Create Milvus collection `nexus_chunks` if missing.
3. Store chunk vectors with metadata:
   - `uri`
   - `chunk_id`
   - `text`
   - `created_by`
   - `visibility`
4. Search by vector and return top matches.
5. Run integration test against `kg-milvus`.
6. Expected: similar text returns the indexed chunk.

## Task 8: Wire API To Persistent Stores Behind A Factory

**Files:**
- Modify: `nexus/api.py`
- Create: `nexus/app_factory.py`
- Test: `tests/unit/test_app_factory.py`

**Steps:**
1. Add `NEXUS_STORAGE_BACKEND=memory|postgres`.
2. Default remains `memory` for fast tests.
3. When `postgres`, instantiate Postgres repository and Neo4j/Milvus adapters.
4. Keep `create_app(repository=...)` test seam intact.
5. Run `python3 -m pytest`.
6. Expected: unit tests pass without external services.

## Task 9: Update Docs And Runbooks

**Files:**
- Modify: `README.md`
- Create: `docs/local-development.md`

**Steps:**
1. Document current recommended startup:
   - ensure `kg-*` services are running.
   - copy `.env.local.example` for host development.
   - run `uvicorn apps.api.main:app --reload`.
   - run `npm run dev` in `apps/web`.
2. Document Docker sidecar mode:
   - copy `.env.docker.example`.
   - run `docker compose -f infrastructure/docker/docker-compose.yml up --build`.
3. Document MinIO login:
   - URL `http://localhost:9001`
   - user `minioadmin`
   - password `minioadmin`
4. Add warning that these are local dev credentials only.
5. Run `python3 -m pytest` and `npm run build`.

## Task 10: Acceptance Check

**Commands:**
- `python3 -m pytest`
- `npm run build` from `apps/web`
- `docker compose -f infrastructure/docker/docker-compose.yml config`
- `RUN_INTEGRATION=1 python3 -m pytest tests/integration`

**Expected:**
- Unit tests pass without Docker dependencies.
- Web build succeeds.
- Compose validates without trying to create duplicate database/vector services.
- Integration tests pass when existing `kg-*` services are healthy.

