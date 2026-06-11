# Smart Campus Graph OS Design

## Goal

Build an interactive Pi-Agent workflow that turns smart campus research material into a governed ontology and knowledge graph. Pi-Agent should be able to independently extract entities and relations, review graph candidates, commit approved knowledge into Neo4j, and answer questions from the graph without relying on an external delivery system.

## Recommended Shape

Use Knowledge OS as the complete graph operating system.

The existing code already provides the right spine:

1. Read files from Cloudreve or local source paths.
2. Parse PDF, DOCX, spreadsheet, Markdown, text, JSON, YAML, and CSV content.
3. Classify smart campus documents as `smart_campus`.
4. Build a traceable extraction context with the `nexus/smart_campus` ontology.
5. Extract entities and relations into candidate batches.
6. Let Pi-Agent review, merge, reject, or enrich candidates.
7. Commit approved candidates to Neo4j with evidence stored in Postgres.
8. Use graph QA, neighborhood traversal, stale evidence checks, and diagnosis workflows to keep improving the graph.

This gives us a self-contained loop: source material -> ontology-guided extraction -> candidate governance -> graph commit -> question answering -> gap discovery -> ontology and graph refinement.

## Ontology Layers

The first ontology seed is `data/ontology/templates/nexus/smart_campus.yaml`.

| Layer | Purpose | Main Concepts |
|---|---|---|
| Standard prior layer | Bring external authority and reusable rules | `Standard`, `Rule`, `Dataset` |
| Physical skeleton layer | Describe where assets are and how systems connect | `Campus`, `Building`, `Floor`, `Space`, `System`, `Equipment` |
| Dynamic sensing layer | Describe telemetry, alarms, and metrics | `Point`, `Metric`, `FaultEvent` |
| Business experience layer | Capture manuals, work orders, SOPs, and diagnosis knowledge | `RootCause`, `WorkOrder`, `Procedure`, `Role` |
| Agent governance layer | Capture Pi-Agent graph operations and review state | `AgentAction`, `CandidateBatch`, `GraphWorkspace` |

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
| Memory tools | Record project assumptions, accepted naming rules, rejected extraction patterns, and open modeling questions |

The existing MCP workflow already covers much of this: `run_candidate_extraction`, `get_candidate_batch`, `update_candidate_items`, `preview_graph_changes`, `commit_candidate_batch`, `ask_knowledge_graph`, `get_knowledge_dashboard`, and batch review tools.

## Pi-Agent Skills

Create reusable prompt-level skills around stable workflows, not one-off commands:

| Skill | Trigger | Output |
|---|---|---|
| Campus ontology initializer | New project, new customer, or new data room | Customer-specific ontology delta and naming conventions |
| Data checklist analyst | Customer data collection discussion | Gap list by static/dynamic/document/standard data |
| Document-to-graph reviewer | After extraction batch is created | Accepted/rejected candidate edits with reasons |
| Fault diagnosis analyst | Alarm, abnormal metric, or incident question | Root-cause chain, impacted spaces/assets, evidence, action plan |
| Graph growth operator | After QA exposes missing nodes, relations, or evidence | Next extraction target, ontology patch, or candidate enrichment action |

Each skill should write durable memory: source files used, ontology version, accepted naming rules, rejected extraction patterns, customer-specific synonyms, and open questions.

## Memory Model

Keep memory explicit and auditable.

| Memory Type | Examples | Storage Target |
|---|---|---|
| Project memory | Customer, campus scope, graph workspace goal, current ingestion scope | Markdown plan files and graph metadata |
| Ontology memory | Concept additions, relation constraints, naming aliases | YAML ontology versions and Neo4j ontology subgraph |
| Evidence memory | Source URI, page/section span, extraction batch, reviewer decision | Postgres `graph_evidence` and candidate tables |
| Interaction memory | User decisions, recurring questions, rejected assumptions | `findings.md`, `progress.md`, and future Agent memory store |
| Operational memory | Frequent fault patterns, diagnosis rules, playbooks | Graph nodes: `Rule`, `Procedure`, `AgentAction` |

Do not hide important modeling decisions only in chat history. If a decision changes the graph, record it in files or graph evidence.

## Native Graph-Building Contract

Pi-Agent should treat every graph update as a governed state transition:

```json
{
  "ontology_id": "smart_campus",
  "graph_workspace": "customer_or_demo_workspace",
  "source_id": "cloudreve_or_local_uri",
  "candidate_batch": {
    "entities": [],
    "relations": [],
    "evidence": []
  },
  "review_decisions": [],
  "commit_result": {
    "created_nodes": 0,
    "created_edges": 0,
    "updated_evidence": 0
  },
  "open_questions": []
}
```

The key rule is simple: extraction produces candidates, review changes candidate state, commit updates the graph, and QA/diagnosis reads only committed graph knowledge plus traceable evidence.

## Initialization Workflow

1. Put source materials into a project folder or Cloudreve collection.
2. Ask Pi-Agent to classify and summarize the materials.
3. Run `smart_campus` extraction on the four seed documents.
4. Review candidates layer by layer: standard prior, physical skeleton, dynamic sensing, business experience, agent governance.
5. Commit only approved candidates.
6. Ask graph QA for gaps: missing topology, missing data types, unsupported diagnosis rules, missing evidence.
7. Patch ontology and rerun extraction for affected documents.
8. Use the resulting graph directly for QA, fault diagnosis, data checklist generation, and next-step planning.

## Testing And Governance

Minimum checks for each iteration:

- Classifier recognizes campus/BMS/EMS/HVAC/Brick/FDD materials as `smart_campus`.
- Template adapter loads `nexus/smart_campus`.
- Extraction context includes campus entity and relation hints.
- Candidate batches move through review before graph commit.
- Every committed relation has evidence.
- Agent diagnosis answers include evidence and uncertainty, not just conclusions.

## Open Questions

1. Should customer-specific ontology deltas live in a separate project YAML layered on top of `nexus/smart_campus`?
2. Should public datasets enter the graph as demo evidence, algorithm validation metadata, or only external references?
3. Which Pi-Agent skill should be implemented first: ontology initializer, candidate reviewer, or fault diagnosis analyst?
