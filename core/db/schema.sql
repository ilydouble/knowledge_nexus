CREATE TABLE IF NOT EXISTS semantic_documents (
    uri TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    summary TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    requested_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS active_batch_id TEXT;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS filename TEXT;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'local';
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS mime_type TEXT;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS size_bytes INTEGER;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS doc_type TEXT;
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0;
-- Pointer to where the full parsed text lives (local URI, cloudreve URI, or future s3:// key).
-- Postgres only stores the preview (text_preview ≤ 400 chars) in semantic_chunks.
ALTER TABLE semantic_documents ADD COLUMN IF NOT EXISTS parsed_text_key TEXT;

CREATE TABLE IF NOT EXISTS semantic_chunks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    document_uri TEXT NOT NULL REFERENCES semantic_documents(uri) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    -- Display preview only (≤ 400 chars). Full text is referenced by semantic_documents.parsed_text_key.
    text TEXT NOT NULL DEFAULT ''
);

ALTER TABLE semantic_chunks ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE semantic_chunks ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE semantic_chunks ADD COLUMN IF NOT EXISTS entities JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE semantic_chunks ADD COLUMN IF NOT EXISTS char_start INTEGER;
ALTER TABLE semantic_chunks ADD COLUMN IF NOT EXISTS char_end INTEGER;

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

CREATE INDEX IF NOT EXISTS idx_semantic_chunks_document_uri ON semantic_chunks(document_uri);
CREATE INDEX IF NOT EXISTS idx_knowledge_links_source_uri ON knowledge_links(source_uri);
CREATE INDEX IF NOT EXISTS idx_knowledge_links_target_uri ON knowledge_links(target_uri);

CREATE TABLE IF NOT EXISTS extraction_batches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_uri TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    template_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    instructions TEXT,
    parent_batch_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    committed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS candidate_ontologies (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    batch_id TEXT NOT NULL REFERENCES extraction_batches(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    review_note TEXT
);

CREATE TABLE IF NOT EXISTS candidate_graph_items (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    batch_id TEXT NOT NULL REFERENCES extraction_batches(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_span JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    status TEXT NOT NULL,
    review_note TEXT
);

CREATE TABLE IF NOT EXISTS graph_evidence (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    graph_item_id TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    template_id TEXT,
    evidence_text TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extraction_batches_source_uri ON extraction_batches(source_uri);
CREATE INDEX IF NOT EXISTS idx_candidate_graph_items_batch_id ON candidate_graph_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_graph_evidence_graph_item_id ON graph_evidence(graph_item_id);
CREATE INDEX IF NOT EXISTS idx_graph_evidence_source_uri ON graph_evidence(source_uri);
