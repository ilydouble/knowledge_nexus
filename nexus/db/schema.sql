CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    uri TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_code TEXT,
    error TEXT
);

ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS error_code TEXT;

CREATE TABLE IF NOT EXISTS semantic_documents (
    uri TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    summary TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    requested_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS semantic_chunks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    document_uri TEXT NOT NULL REFERENCES semantic_documents(uri) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_links (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_uri TEXT NOT NULL,
    target_uri TEXT NOT NULL,
    relation TEXT NOT NULL,
    layer TEXT NOT NULL,
    owner_scope TEXT NOT NULL,
    source_file_uri TEXT NOT NULL,
    visibility TEXT NOT NULL,
    created_by TEXT NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_uri ON ingestion_jobs(uri);
CREATE INDEX IF NOT EXISTS idx_semantic_chunks_document_uri ON semantic_chunks(document_uri);
CREATE INDEX IF NOT EXISTS idx_knowledge_links_source_uri ON knowledge_links(source_uri);
CREATE INDEX IF NOT EXISTS idx_knowledge_links_target_uri ON knowledge_links(target_uri);
