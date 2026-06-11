# Smart Campus Graph OS Design

## Goal

Build an interactive Pi-Agent workflow that turns smart campus research material into a governed ontology and knowledge graph. The same workflow should support direct graph QA in Knowledge OS and export curated graph assets to KGraph for project delivery.

## Recommended Shape

Use Knowledge OS as the working graph operating system and KGraph as the delivery graph refinement system.

Knowledge OS should own the iterative loop:

1. Read files from Cloudreve or local source paths.
2. Classify smart campus documents as `smart_campus`.
3. Build KGraph extraction context with the `nexus/smart_campus` ontology.
4. Extract entities and relations into candidate batches.
5. Let Pi-Agent review, merge, reject, or enrich candidates.
6. Commit approved candidates to Neo4j with evidence.
7. Answer questions and discover gaps through graph QA.
8. Export ontology, graph slices, evidence, and unresolved issues to KGraph.

KGraph should own delivery hardening:

1. Refine customer-specific concepts, IDs, naming rules, and visual graph structure.
2. Validate final topology, business rules, diagnosis chains, and customer acceptance views.
3. Package project deliverables for demonstration, handover, and operation.

## Ontology Layers

The first ontology seed is `data/ontology/templates/nexus/smart_campus.yaml`.

| Layer | Purpose | Main Concepts |
|---|---|---|
| Standard prior layer | Bring external authority and reusable rules | `Standard`, `Rule`, `Dataset` |
| Physical skeleton layer | Describe where assets are and how systems connect | `Campus`, `Building`, `Floor`, `Space`, `System`, `Equipment` |
| Dynamic sensing layer | Describe telemetry, alarms, and metrics | `Point`, `Metric`, `FaultEvent` |
| Business experience layer | Capture manuals, work orders, SOPs, and diagnosis knowledge | `RootCause`, `WorkOrder`, `Procedure`, `Role`, `AgentAction` |

Keep spatial containment separate from service topology. Use `CONTAINS` and `PART_OF` for location hierarchy. Use `FEEDS`, `POWERS`, `CONTROLS`, `CONNECTED_TO`, and `HAS_POINT` for operational topology.

## Pi-Agent Tools

The client should expose these tool groups over MCP or local command adapters:

| Tool Group | Responsibility |
|---|---|
| Source tools | List source files, parse selected documents, fetch Cloudreve/local content |
| Ontology tools | Load `smart_campus` ontology, inspect concepts and relations, propose ontology patches |
| Candidate tools | Run extraction, inspect candidate batches, accept/reject/update candidate items |
| Graph tools | Preview graph changes, commit approved batches, query graph neighborhoods, detect stale evidence |
| Diagnosis tools | Given event evidence, traverse topology, retrieve procedures, produce root-cause reports |
| Export tools | Export ontology, graph slices, evidence references, unresolved questions, and KGraph import payloads |

The existing MCP workflow already covers much of this: `run_candidate_extraction`, `get_candidate_batch`, `update_candidate_items`, `preview_graph_changes`, `commit_candidate_batch`, `ask_knowledge_graph`, `get_knowledge_dashboard`, and batch review tools.

## Pi-Agent Skills

Create reusable prompt-level skills around stable workflows, not one-off commands:

| Skill | Trigger | Output |
|---|---|---|
| Campus ontology initializer | New project, new customer, or new data room | Customer-specific ontology delta and naming conventions |
| Data checklist analyst | Customer data collection discussion | Gap list by static/dynamic/document/standard data |
| Document-to-graph reviewer | After extraction batch is created | Accepted/rejected candidate edits with reasons |
| Fault diagnosis analyst | Alarm, abnormal metric, or incident question | Root-cause chain, impacted spaces/assets, evidence, action plan |
| KGraph handoff packager | Before delivery iteration | Export bundle and unresolved modeling questions |

Each skill should write durable memory: source files used, ontology version, accepted naming rules, rejected extraction patterns, customer-specific synonyms, and open questions.

## Memory Model

Keep memory explicit and auditable.

| Memory Type | Examples | Storage Target |
|---|---|---|
| Project memory | Customer, campus scope, delivery goal, KGraph handoff preference | Markdown plan files and graph metadata |
| Ontology memory | Concept additions, relation constraints, naming aliases | YAML ontology versions and Neo4j ontology subgraph |
| Evidence memory | Source URI, page/section span, extraction batch, reviewer decision | Postgres `graph_evidence` and candidate tables |
| Interaction memory | User decisions, recurring questions, rejected assumptions | `findings.md`, `progress.md`, and future Agent memory store |
| Operational memory | Frequent fault patterns, diagnosis rules, playbooks | Graph nodes: `Rule`, `Procedure`, `AgentAction` |

Do not hide important modeling decisions only in chat history. If a decision changes the graph, record it in files or graph evidence.

## KGraph Export Contract

Until KGraph's exact import format is known, use a neutral handoff contract:

```json
{
  "ontology_id": "smart_campus",
  "ontology_version": "1.0",
  "concepts": [],
  "relations": [],
  "graph_slice": {
    "nodes": [],
    "edges": []
  },
  "evidence": [],
  "review_decisions": [],
  "open_questions": []
}
```

Later adapters can map this to Neo4j Cypher, RDF/OWL/Turtle, JSON-LD, or a KGraph-specific schema.

## Initialization Workflow

1. Put source materials into a project folder or Cloudreve collection.
2. Ask Pi-Agent to classify and summarize the materials.
3. Run `smart_campus` extraction on the four seed documents.
4. Review candidates layer by layer: standard prior, physical skeleton, dynamic sensing, business experience.
5. Commit only approved candidates.
6. Ask graph QA for gaps: missing topology, missing data types, unsupported diagnosis rules, missing evidence.
7. Patch ontology and rerun extraction for affected documents.
8. Export the first KGraph handoff bundle.

## Testing And Governance

Minimum checks for each iteration:

- Classifier recognizes campus/BMS/EMS/HVAC/Brick/FDD materials as `smart_campus`.
- Template adapter loads `nexus/smart_campus`.
- KGraph context includes campus entity and relation hints.
- Every committed relation has evidence.
- Agent diagnosis answers include evidence and uncertainty, not just conclusions.

## Open Questions

1. Which KGraph import format should become the first concrete adapter?
2. Should public datasets enter the graph as demo evidence, algorithm validation metadata, or only external references?
3. Should customer-specific ontology deltas live in a separate project YAML layered on top of `nexus/smart_campus`?
