---
name: knowledge-graph
description: Use this skill when the user wants to build, extract from, merge, query, or dynamically grow a knowledge graph. Trigger on tasks like "build a knowledge graph for X", "extract entities and relations from this text", "merge two knowledge graphs", "query the knowledge graph", "grow the knowledge graph with new information", or "define an ontology for X". This skill provides the full pipeline from schema construction through iterative graph growth.
---

# Knowledge Graph Skill

## Overview

This skill provides a complete pipeline for building and maintaining knowledge graphs. It covers ontology construction, information extraction, graph fusion, querying, and dynamic growth — all orchestrated through Python scripts with LLM-powered extraction performed via deer-flow agent tools.

## Core Capabilities

- **Ontology Building**: Define concept types and relation types for a domain
- **Graph Extraction**: Extract entities, relations, and attributes from text/documents
- **Graph Fusion**: Align and merge graphs from multiple sources
- **Graph Querying**: Traverse, search, and analyze graph structure
- **Dynamic Growth**: Incrementally extend graphs with new information, track versions, detect patterns

## Directory Structure

```
knowledge-graph/
├── SKILL.md (this file)
└── scripts/
    ├── ontology_builder.py   - Schema/ontology construction
    ├── graph_extractor.py   - Entity/relation extraction, dedup, stats
    ├── graph_fusion.py      - Graph alignment and merging
    ├── graph_growth.py      - Incremental growth, versioning, pattern detection
    └── graph_query.py       - Traversal, path finding, pattern matching
└── references/
    └── extraction-prompts.md  - LLM prompt templates for extraction
```

## Workflow

### Step 1: Define the Ontology (Schema)

Before extracting any graph, define the concept and relation types. This ensures consistency.

```bash
# View default ontology
python /mnt/skills/public/knowledge-graph/scripts/ontology_builder.py --action list

# Suggest ontology for a domain
python /mnt/skills/public/knowledge-graph/scripts/ontology_builder.py \
  --action suggest --domain "artificial intelligence"

# Build custom ontology and save
python /mnt/skills/public/knowledge-graph/scripts/ontology_builder.py \
  --action build --domain "computer science" \
  --concepts "Algorithm,Model,Dataset" \
  --relations "USES,MUTUALLY_EXCLUSIVE" \
  --output ontology.json
```

**Before extraction**, the model using this skill should use the deer-flow LLM tools to analyze the domain and suggest appropriate entity/relation types beyond the defaults. Consult `references/extraction-prompts.md` for prompt templates.

### Step 2: Extract Entities and Relations from Text

Use the deer-flow LLM agent to extract structured graph data from documents, articles, or text. The script provides the template and validation.

```bash
# The extraction is done via LLM — construct the prompt based on your ontology
# Then validate the result:
python /mnt/skills/public/knowledge-graph/scripts/graph_extractor.py \
  --action validate --input extracted_graph.json --schema ontology.json

# Get graph statistics
python /mnt/skills/public/knowledge-graph/scripts/graph_extractor.py \
  --action stats --input extracted_graph.json

# Deduplicate nodes
python /mnt/skills/public/knowledge-graph/scripts/graph_extractor.py \
  --action dedup --input extracted_graph.json --strategy merge \
  --output deduped_graph.json
```

**LLM Extraction Prompt Pattern** (from `references/extraction-prompts.md`):
- Provide the ontology as context
- Give the source text
- Ask for JSON output with `nodes` (id, label, type, attributes) and `edges` (source, target, relation, attributes)
- Use entity resolution hints to deduplicate during extraction

### Step 3: Merge Multiple Extraction Results

When you have extracted graphs from multiple sources, align and merge them.

```bash
# Align nodes between two graphs (find same entities)
python /mnt/skills/public/knowledge-graph/scripts/graph_fusion.py \
  --action align --graph1 source1.json --graph2 source2.json \
  --strategy fuzzy --threshold 0.85

# Merge with conflict resolution
python /mnt/skills/public/knowledge-graph/scripts/graph_fusion.py \
  --action merge --graph1 source1.json --graph2 source2.json \
  --output merged.json

# Consolidate duplicate relations
python /mnt/skills/public/knowledge-graph/scripts/graph_fusion.py \
  --action consolidate --input merged.json \
  --strategy majority --output consolidated.json
```

### Step 4: Query and Analyze the Graph

```bash
# Find all nodes of a type
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action nodes --type "Person" --input graph.json

# Get neighbors of a node (BFS up to depth N)
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action neighbors --node "person_abc123" --depth 2 --input graph.json

# Find shortest path between two nodes
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action path --source "node_a" --target "node_b" --input graph.json

# Match a pattern: Person->DISCOVERED->Concept
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action pattern --pattern "Person->DISCOVERED->Concept" --input graph.json

# Extract subgraph around seed nodes
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action subgraph --seeds "node1,node2" --depth 1 --input graph.json

# Export to Neo4j Cypher format
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action export --format neo4j --input graph.json --output import.cypher
```

### Step 5: Dynamic Graph Growth

Iteratively extend the graph with new information, track versions, and detect emerging patterns.

```bash
# Add new nodes and edges
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action add --input graph.json --nodes new_data.json --edges new_edges.json \
  --output graph_v2.json

# Generate evolution strategy (for LLM-guided expansion)
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action evolve --input graph.json \
  --prompt "Add entities about deep learning and neural networks"

# Detect emerging patterns (hubs, new relations, new types)
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action detect-emerging --input graph.json --top-n 5

# Version control
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action version --input graph.json --version v1.1 --message "Added AI subfield entities"

# Compare two versions
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action compare --graph1 graph_v1.json --graph2 graph_v2.json

# Find hub nodes
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action hub-detection --input graph.json --top-n 10
```

### Step 6: Full Pipeline — End-to-End Example

```bash
# 1. Define ontology for the domain
python /mnt/skills/public/knowledge-graph/scripts/ontology_builder.py \
  --action build --domain "nlp research" \
  --output ontology.json

# 2. Extract from document 1 (via LLM)
# ... LLM extraction ...

# 3. Validate and dedup
python /mnt/skills/public/knowledge-graph/scripts/graph_extractor.py \
  --action validate --input doc1_graph.json --schema ontology.json

# 4. Extract from document 2 (via LLM)
# ... LLM extraction ...

# 5. Merge results
python /mnt/skills/public/knowledge-graph/scripts/graph_fusion.py \
  --action merge --graph1 doc1_graph.json --graph2 doc2_graph.json \
  --output merged.json

# 6. Add from document 3
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action add --input merged.json --nodes doc3_nodes.json --edges doc3_edges.json \
  --output graph_v2.json

# 7. Analyze
python /mnt/skills/public/knowledge-graph/scripts/graph_query.py \
  --action stats --input graph_v2.json

# 8. Detect hubs and emerging patterns
python /mnt/skills/public/knowledge-graph/scripts/graph_growth.py \
  --action detect-emerging --input graph_v2.json
```

## Parameters Reference

### ontology_builder.py

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--action` | Yes | `list`, `suggest`, `export`, `build` |
| `--domain` | For `suggest`/`build` | Domain description |
| `--concepts` | No | Comma-separated custom concept types |
| `--relations` | No | Comma-separated relations (NAME:SRC:TGT) |
| `--format` | No | Export format: `json`, `yaml` |
| `--output` | No | Output file path |

### graph_extractor.py

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--action` | Yes | `validate`, `dedup`, `stats`, `convert`, `merge` |
| `--input` | Yes | Input graph JSON file |
| `--input2` | For merge | Second graph file |
| `--schema` | For validate | Ontology JSON file |
| `--output` | No | Output file path |
| `--strategy` | No | Dedup strategy: `merge`, `remove_duplicates` |
| `--mode` | For merge | `json` or `prompt` |

### graph_fusion.py

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--action` | Yes | `align`, `merge`, `align-and-merge`, `consolidate` |
| `--graph1` | For align/merge | First graph JSON |
| `--graph2` | For align/merge | Second graph JSON |
| `--input` | For consolidate | Input graph JSON |
| `--output` | No | Output file path |
| `--strategy` | No | `exact`, `fuzzy`, `type`, `majority` |
| `--threshold` | No | Similarity threshold (default: 0.8) |

### graph_growth.py

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--action` | Yes | `add`, `evolve`, `detect-emerging`, `version`, `compare`, `hub-detection` |
| `--input` | For most actions | Input graph JSON |
| `--graph1`/`--graph2` | For compare | Two graph versions |
| `--nodes`/`--edges` | For add | New data files |
| `--output` | No | Output file path |
| `--version` | For version | Version string |
| `--prompt` | For evolve | LLM extraction prompt |
| `--top-n` | No | Top N results (default: 10) |

### graph_query.py

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--action` | Yes | `nodes`, `neighbors`, `path`, `pattern`, `subgraph`, `stats`, `export` |
| `--input` | Yes | Input graph JSON |
| `--type`/`--label` | For nodes | Filter by type or label |
| `--node`/`--source`/`--target` | For neighbors/path | Node IDs |
| `--pattern` | For pattern | Pattern: `TYPE->REL->TYPE` |
| `--seeds` | For subgraph | Comma-separated seed IDs |
| `--depth` | For traversal | BFS depth (default: 1) |
| `--format` | For export | `neo4j`, `json-ld` |

## Graph JSON Format

The skill uses a standard JSON graph format:

```json
{
  "nodes": [
    {
      "id": "unique_identifier",
      "label": "Display Name",
      "type": "Person",
      "description": "Optional description",
      "attributes": { "key": "value" }
    }
  ],
  "edges": [
    {
      "source": "node_id_1",
      "target": "node_id_2",
      "relation": "WORKS_AT",
      "attributes": { "since": "2020" }
    }
  ],
  "history": [
    { "action": "add", "timestamp": "2026-04-23T12:00:00Z", "new_nodes": 5 }
  ]
}
```

## LLM Extraction Guidance

When using LLM tools to extract graph data, instruct the model to:

1. **Read the ontology** from `ontology.json` or the suggested types
2. **Identify entities** matching the concept types
3. **Identify relations** matching the relation types
4. **Assign stable IDs** using a hash of (type, label) for deduplication
5. **Include attributes** for each entity and relation
6. **Provide confidence scores** for uncertain extractions

See `references/extraction-prompts.md` for ready-made prompt templates.

## Notes

- The scripts handle JSON I/O, validation, deduplication, and analysis — they do NOT perform the actual LLM-based text extraction
- LLM extraction is orchestrated through deer-flow's agent tools (code interpreter, LLM calls) following the templates in this skill
- For large-scale production graphs, export to a graph database (Neo4j, NebulaGraph) via the export action
- The `history` field in graph JSON tracks all modifications for audit trail
- Graph versioning supports reproducibility and rollback
