---
name: knowledge-os
description: Use to operate the Knowledge OS knowledge graph — extract entities/relations from Cloudreve documents, review candidate batches, commit them into the Neo4j graph, ask natural-language questions, and govern (mark-deleted / purge) sources. Trigger when the user wants to ingest a document into the knowledge base, build/query the knowledge graph, review or commit extraction candidates, or clean up stale knowledge.
---

# Knowledge OS

Drive the Knowledge OS **extract → review → commit → query** workflow through
the `kn` CLI, a thin client over the backend REST API.

## Prerequisite

The Knowledge OS backend must be running and reachable:

```bash
./start.sh            # from the knowledge_nexus repo root
```

`kn` talks to `http://localhost:8000` by default. Point it elsewhere with the
`KN_API_URL` environment variable. Run `kn` from this skill directory (the
script sits next to this file), or call it by full path:

```bash
python3 kn dashboard          # quick health check + counts
```

If `kn dashboard` errors with "Cannot reach …", the backend is not running —
tell the user to run `./start.sh` first.

## Core workflow

Knowledge is written under a controlled pipeline. Nothing lands in the graph
until a batch is **committed**. The normal sequence:

1. **Extract** candidates from a document:
   `python3 kn extract "cloudreve://path/to/report.pdf" --instructions "focus on risks"`
   Returns a `batch_id` plus the proposed entities/relations.
2. **Review** the batch — inspect items, then accept/reject:
   - `python3 kn batch <batch_id>` to see items and their ids
   - `python3 kn review <batch_id> --accept ID1 --accept ID2 --reject ID3`
   - or bulk: `python3 kn accept-all <batch_id>` / `python3 kn reject-all <batch_id>`
3. **Preview** the exact graph changes a commit would make (no write):
   `python3 kn preview <batch_id>`
4. **Commit** accepted items into the Neo4j graph:
   `python3 kn commit <batch_id>`

## Querying the graph

- `python3 kn ask "谁负责智慧校园项目?"` — natural-language Q&A over the
  committed graph (needs Neo4j + an LLM API key configured on the backend).
- `python3 kn graph` — dump the full graph; `--uri <uri>` for a 1-hop view.
- `python3 kn evidence --item <graph_item_id>` or `--source <uri>` — trace
  which source text backs a piece of knowledge.

## Governance (use with care)

Soft governance — these only affect Postgres metadata; they do **not**
physically wipe Neo4j nodes unless a re-scan runs:

- `python3 kn stale` — report stale/purged evidence grouped by source.
- `python3 kn mark-deleted "<uri>"` — mark a source removed, stale its evidence.
- `python3 kn purge "<uri>" [--mode knowledge]` — purge evidence for a source.

Hard delete — **irreversible**, physically removes graph data:

- `python3 kn delete-graph "<uri>"` — DETACH DELETE the file node, its edges,
  and any orphaned entity nodes from Neo4j, then purge its Postgres evidence so
  both stores stay in sync. Only run after the user explicitly confirms the URI.

> File-source operations (drive authorization, scanning Cloudreve so new files
> are discovered) live in the separate **cloudreve-io** skill. Use that to get
> a `cloudreve://…` URI, then bring it here to extract.

## Command reference

| Command | Purpose |
|---|---|
| `dashboard` | counts, item-status breakdown, stale alerts |
| `batches [--status S] [--source-uri U] [--limit N]` | list candidate batches |
| `batch <id>` | show one batch and its items |
| `extract <uri> [--instructions T] [--template ID]…` | auto-extract candidates |
| `review <id> [--accept ID]… [--reject ID]…` | accept/reject specific items |
| `accept-all <id>` / `reject-all <id>` | bulk decision |
| `preview <id>` | dry-run the graph diff |
| `commit <id>` | write accepted items into the graph |
| `ask <question>` | natural-language graph Q&A |
| `graph [--uri U]` | full graph or 1-hop neighborhood |
| `evidence [--item ID] [--source U]` | evidence trace |
| `stale` | stale/purged evidence report |
| `mark-deleted <uri>` / `purge <uri> [--mode M]` | source governance (soft) |
| `delete-graph <uri>` | hard-delete Neo4j nodes/edges + purge evidence |

## Safety rules

- Never call `commit` before the user has reviewed the batch (or explicitly
  asked for `accept-all` + commit). Show `preview` output first when unsure.
- `purge` and `mark-deleted` are destructive to metadata — confirm the exact
  `uri` with the user before running them.
- `delete-graph` is an irreversible hard delete of graph data — always confirm
  the exact `uri` with the user and never run it speculatively.
