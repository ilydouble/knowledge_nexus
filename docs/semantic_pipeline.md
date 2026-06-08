# Semantic Processing Pipeline

## Overview

The semantic processing pipeline handles the complete flow from file upload to knowledge extraction and storage.

```
Cloudreve Upload → SSE Event → Worker → Download → Parse → Classify → Build kgraph context → Extract → Store → Link documents on demand
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Semantic Processing Pipeline                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐             │
│  │  Cloudreve  │───→│   Worker    │───→│  Download   │             │
│  │   (SSE)     │    │  (Events)   │    │   File      │             │
│  └─────────────┘    └─────────────┘    └─────────────┘             │
│                                               │                     │
│                                               ▼                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                   Content Parser                         │       │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐     │       │
│  │  │   PDF   │  │  DOCX   │  │  TEXT   │  │   ...   │     │       │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘     │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                               │                     │
│                                               ▼                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                Knowledge Extractor                       │       │
│  │  ┌─────────────────┐    ┌─────────────────┐             │       │
│  │  │ knowledge-graph │    │      LLM        │             │       │
│  │  │     skill       │    │  (OpenAI)       │             │       │
│  │  └─────────────────┘    └─────────────────┘             │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                               │                     │
│                                               ▼                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                    Storage Layer                         │       │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │       │
│  │  │ Neo4j   │  │ Milvus  │  │ Postgres │                 │       │
│  │  │ (Graph) │  │(Vector) │  │ (Meta)   │                 │       │
│  │  └─────────┘  └─────────┘  └─────────┘                  │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Content Parser (`nexus/services/content_parser.py`)

Parses various file formats and extracts text content.

**Supported Formats:**
- PDF (via pdfplumber)
- Word Documents (via python-docx)
- Plain Text, Markdown, CSV, JSON

**Output:**
```python
@dataclass
class ParsedContent:
    text: str           # Full extracted text
    metadata: dict      # File metadata (pages, size, etc.)
    chunks: list[str]   # Text chunks for embedding
    file_type: str      # Detected file type
```

### 2. Document Classifier (`nexus/services/document_classifier.py`)

Classifies each parsed file before graph extraction.

**Output:**
- `doc_type`: business/document category such as `technical_doc`, `meeting_minutes`, `report`, or `contract`
- `strategy`: `llm_extract` or `structural_summary`
- `confidence` and `signals`: traceable reasons for the decision

The classifier decides which ontology family and extraction strategy should be used. It does not merge entities across documents.

### 3. KGraph Context Builder (`nexus/services/kgraph_context.py`)

Builds the structured JSON contract handed to downstream graph extraction. This is the pre-filtering layer: it keeps high-signal sections/windows and preserves enough provenance for later replay, audit, and cross-document merge work.

**Output shape:**
```json
{
  "document_id": "doc_<stable_hash>",
  "source_id": "cloudreve://team/document.md",
  "extraction_batch_id": "<uuid>",
  "classification": {
    "doc_type": "technical_doc",
    "business_domain": "engineering",
    "ontology_id": "technical_doc",
    "strategy": "llm_extract",
    "confidence": 0.83,
    "signals": ["filename:api→technical_doc"],
    "should_extract": true
  },
  "sections": [
    {
      "section_id": "doc_<stable_hash>_section_1",
      "title": "Page 3",
      "relevance_score": 0.92,
      "text": "...",
      "source_span": {
        "page": 3,
        "start_char": 120,
        "end_char": 850
      },
      "entity_hints": ["Component", "API", "Database"],
      "relation_hints": ["DEPENDS_ON", "CALLS", "STORES_IN"]
    }
  ],
  "metadata": {
    "published_at": null,
    "valid_from": null,
    "valid_to": null,
    "version": null
  }
}
```

The context builder intentionally does not solve cross-document entity merging. It only reserves `document_id`, `source_id`, `extraction_batch_id`, source spans, timestamps, and version metadata so a later disambiguation or graph-maintenance stage can merge evidence safely.

### 4. Knowledge Extractor (`nexus/services/knowledge_extractor.py`)

Extracts structured knowledge from text using LLM and knowledge-graph skill.

**Features:**
- Ontology-based extraction
- Document type templates (academic, technical, meeting, report)
- Entity and relation extraction
- Summary and tag generation

**Output:**
```python
@dataclass
class ExtractedKnowledge:
    summary: str
    tags: list[str]
    entities: list[dict]    # [{id, label, type, description}]
    relations: list[dict]   # [{source, target, relation, evidence}]
    key_points: list[dict]
    confidence: float
```

### 5. Semantic Pipeline (`nexus/services/pipeline.py`)

Coordinates the complete processing flow.

**Flow:**
1. Download file from Cloudreve
2. Parse content based on file type
3. Classify document type and extraction strategy
4. Build compact kgraph context with relevant sections and provenance
5. Extract knowledge from the filtered context using LLM
6. Store in Neo4j (graph) and Milvus (vectors)

### 6. DocLinker (`nexus/services/doc_linker.py`)

Creates document-to-document links after documents have already been processed. It compares extracted entity lists, finds document pairs with enough shared entities, and writes a `KnowledgeLink` through the repository.

Default behavior is deterministic and local: shared entities produce a `相似` link with the shared entities recorded in the note. The service also supports optional LLM relationship typing when an API key and HTTP client are provided, using the relation set `引用` / `补充` / `扩展` / `冲突` / `相似`.

Manual trigger:

```bash
curl -X POST "http://localhost:8000/api/documents/link?min_shared_entities=1"
```

DocLinker is a graph-maintenance step, not part of the per-document extraction path. It can be run on demand after ingestion or scheduled later.

### 7. Worker (`nexus/worker.py`)

Listens for Cloudreve SSE events and triggers processing.

**Processable Events:**
- `create` - New file uploaded
- `update` - File modified
- `modify` - File modified
- `rename` - File renamed

## Knowledge-Graph Skill Integration

The pipeline integrates with the `knowledge-graph` skill for:

1. **Ontology Building** - Define concept and relation types
2. **Graph Extraction** - Template-based entity/relation extraction
3. **Graph Fusion** - Merge knowledge from multiple sources
4. **Graph Query** - Traverse and analyze the knowledge graph

## Document Type Templates

Different document types use different extraction templates:

| Document Type | Entity Types | Focus Areas |
|--------------|--------------|-------------|
| academic_paper | Researcher, Method, Dataset, Metric | Research question, methodology, conclusions |
| technical_doc | Component, API, Database, Framework | Architecture, dependencies, interfaces |
| meeting_minutes | Person, Task, Decision, Deadline | Decisions, action items, participants |
| report | Metric, Project, Risk, Milestone | Key metrics, progress, recommendations |

## Configuration

Required environment variables in `.env`:

```bash
# Cloudreve
CLOUDREVE_BASE_URL=http://localhost:5212
CLOUDREVE_TOKEN=<your-token>

# Storage
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=admin123

MILVUS_HOST=localhost
MILVUS_PORT=19530

# LLM (for knowledge extraction)
OPENAI_API_KEY=<your-api-key>
```

## Usage

### Start Worker

```bash
python -m nexus.worker
```

### Test Pipeline

```bash
python test_pipeline.py
```

### Manual Processing (via API)

```bash
curl -X POST "http://localhost:8000/api/ingestion/sync" \
  -H "Content-Type: application/json" \
  -d '{"uri": "cloudreve://my/document.pdf"}'
```

## Output Example

When a file is processed:

```
INFO:nexus.worker:Processing file: cloudreve://my/report.pdf (event: create)
INFO:nexus.pipeline:Downloading file: cloudreve://my/report.pdf
INFO:nexus.pipeline:Parsing content: report.pdf
INFO:nexus.pipeline:Extracting knowledge (type: report)
INFO:nexus.pipeline:Storing knowledge
INFO:nexus.worker:Successfully processed cloudreve://my/report.pdf: entities=8, relations=5, chunks=12, time=2340ms
```

## Future Enhancements

1. **More file formats** - Images (OCR), Audio (transcription), Video
2. **Better embedding** - Use OpenAI embeddings instead of deterministic
3. **Incremental updates** - Only process changed parts
4. **Quality scoring** - Confidence-based filtering
5. **Auto-linking** - Suggest related documents
