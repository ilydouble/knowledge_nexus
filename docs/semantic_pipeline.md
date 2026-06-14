# Semantic Processing Pipeline

The semantic pipeline is now an explicit workflow driven by the REST API, MCP
tools, or the Pi-Agent skill. There is no background event consumer or
automatic ingestion queue.

```text
Cloudreve URI / uploaded file / local path
  -> CandidateExtractionPipeline
  -> FileGate
  -> ContentParser
  -> DocumentClassifier
  -> KnowledgeExtractor
  -> Postgres semantic_documents + semantic_chunks
  -> Postgres extraction_batches + candidate_graph_items
  -> Pi-Agent / human review
  -> GraphCommitService
  -> Neo4j graph + Postgres graph_evidence
```

## Entry Points

- `POST /api/admin/candidates/extract` extracts from a `cloudreve://` URI.
- `POST /api/admin/candidates/extract/file` extracts from an uploaded file.
- `POST /api/admin/candidates/extract/path` extracts from a server-side local path.
- MCP exposes the same flow through `run_candidate_extraction`,
  `get_candidate_batch`, `update_candidate_items`,
  `preview_graph_changes`, and `commit_candidate_batch`.
- `skills/knowledge-os/kn` is the Pi-Agent-friendly CLI wrapper around these
  API endpoints.

Cloudreve browsing and scanning are source-discovery helpers only. A scan
returns discovered file URIs; it does not auto-extract documents.

## Extraction Stages

1. Resolve content bytes from the caller-provided upload, local path, or
   Cloudreve URI.
2. Use `FileGate` to skip formats with no useful text.
3. Parse text from PDF, DOCX, Excel, TXT, Markdown, CSV, JSON, and YAML.
4. Classify the document and select an extraction strategy.
5. Run LLM extraction using Hyper-Extract YAML templates, with map-reduce for
   long documents.
6. Persist document-level summary, tags, entities, and segment text in
   Postgres.
7. Persist extracted nodes and edges as reviewable candidate items.

## Storage Responsibilities

- Cloudreve remains the canonical source for original files.
- `semantic_documents` stores file-level metadata, summary, tags, extracted
  entities, content hash, MIME type, and document type.
- `semantic_chunks` stores extracted text windows plus chunk summaries, tags,
  entities, and character spans.
- `extraction_batches` and `candidate_graph_items` store uncommitted review
  candidates.
- `graph_evidence` stores committed evidence provenance.
- Neo4j stores the accepted graph projection.
- Milvus is available as a vector store, but extracted chunks must be explicitly
  embedded and upserted before vector search has useful data.

## Review And Commit

Extraction never writes directly to Neo4j. A candidate batch must be reviewed:

```bash
python skills/knowledge-os/kn extract-file ./report.md
python skills/knowledge-os/kn batch <batch_id>
python skills/knowledge-os/kn accept-all <batch_id>
python skills/knowledge-os/kn preview <batch_id>
python skills/knowledge-os/kn commit <batch_id>
```

The commit step is idempotent for graph item IDs and evidence records.
