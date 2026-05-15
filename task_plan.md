# Task Plan: Persistent Ingestion Visibility

## Goal
Make uploaded Cloudreve documents observable after processing: shared Postgres-backed state, ingestion status, document listing, and a usable Web console view.

## Phases
- [complete] Phase 1: Add failing tests for job status, document APIs, and worker shared repository behavior.
- [complete] Phase 2: Implement repository status methods and Postgres-safe schema updates.
- [complete] Phase 3: Wire API and worker to shared repository and processing status updates.
- [complete] Phase 4: Update Web console to show documents, jobs, and knowledge details.
- [complete] Phase 5: Verify with unit tests and frontend build, then commit scoped changes.

## Decisions
- Keep `memory` supported for tests and quick demos.
- Make Postgres the recommended persistent runtime backend.
- Do not require Neo4j/Milvus success for the basic “is my document processed?” view.

## Errors Encountered
| Error | Attempt | Resolution |
|---|---|---|
| `python scripts/init_postgres.py` could not import `nexus` | Ran script directly | Used `python -m scripts.init_postgres` from repo root |
