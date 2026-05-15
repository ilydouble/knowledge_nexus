# Progress

## 2026-05-15
- Started persistent ingestion visibility implementation.
- Confirmed current runtime issue: worker and API use separate in-memory repositories, so uploaded document results are not visible in the API/Web console.
- Added tests and backend implementation for ingestion job status updates, `/api/ingestion/jobs`, `/api/documents`, and worker use of configured repository builder.
- Verified targeted backend tests: `python -m pytest tests/unit/test_repository_and_services.py tests/unit/test_api.py tests/unit/test_worker.py` passed.
- Rebuilt Web console as a processing workbench with document list, job list, knowledge detail, manual Cloudreve processing, demo text indexing, and GraphRAG query.
- Added local CORS support for `localhost:5173`.
- Set local `.env` to `NEXUS_STORAGE_BACKEND=postgres` and initialized schema with `python -m scripts.init_postgres`.
- Verified full unit tests and Web build: `python -m pytest tests/unit` passed; `npm run build --prefix apps/web` passed.
