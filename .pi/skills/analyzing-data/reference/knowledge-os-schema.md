# Knowledge OS Warehouse Reference

This document describes the relational database schema available in the Knowledge OS warehouse (PostgreSQL). Use these tables to answer questions about processed documents, extraction metadata, and semantic archives.

## Core Tables

### `semantic_documents`
Stores document-level metadata and summaries.

| Column | Type | Description |
|---|---|---|
| `uri` | TEXT | Primary Key. The unique identifier (e.g., `local://...`, `cloudreve://...`) |
| `filename` | TEXT | The display name of the file |
| `source_type` | TEXT | `local` or `cloudreve` |
| `mime_type` | TEXT | Original file MIME type (e.g., `application/pdf`) |
| `size_bytes` | BIGINT | File size in bytes |
| `doc_type` | TEXT | Classified document type (e.g., `Technical Report`, `Legal Contract`) |
| `summary` | TEXT | LLM-generated high-level summary of the entire document |
| `tags` | JSONB | Array of keyword tags (strings) |
| `entities` | JSONB | Array of key entity objects extracted at the document level |
| `chunk_count` | INTEGER | Number of segments this document was split into |
| `created_at` | TIMESTAMP | When the document was first indexed |
| `updated_at` | TIMESTAMP | Last update time |

### `semantic_chunks`
Stores segment-level summaries and character offsets for large documents.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary Key |
| `document_uri` | TEXT | Foreign Key to `semantic_documents(uri)` |
| `chunk_index` | INTEGER | Order of the segment (0-based) |
| `text` | TEXT | The raw text content of this chunk |
| `summary` | TEXT | LLM-generated summary of this specific chunk |
| `tags` | JSONB | Array of keyword tags for this chunk |
| `entities` | JSONB | Array of entities extracted from this chunk |
| `char_start` | INTEGER | Start position in the original full text |
| `char_end` | INTEGER | End position in the original full text |

## Common Queries

### 1. Find documents by entity tag
```sql
SELECT filename, doc_type, summary
FROM semantic_documents
WHERE tags ? 'AI' OR tags ? 'Security';
```

### 2. Get detailed segments for a specific file
```sql
SELECT chunk_index, summary, tags
FROM semantic_chunks
WHERE document_uri = 'local:///path/to/file.pdf'
ORDER BY chunk_index;
```

### 3. Aggregate document types
```sql
SELECT doc_type, COUNT(*) as count
FROM semantic_documents
GROUP BY doc_type
ORDER BY count DESC;
```
