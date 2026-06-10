"""Knowledge Nexus MCP Server.

Exposes the Neo4j knowledge graph and Postgres document metadata as MCP tools
so that Claude Code (and any other MCP-capable agent) can query them directly.

Usage:
    conda run -n nexus python -m nexus.mcp_server

Claude Code ~/.claude/claude_desktop_config.json entry:
    {
      "mcpServers": {
        "knowledge-nexus": {
          "command": "/opt/miniconda3/envs/nexus/bin/python",
          "args": ["-m", "nexus.mcp_server"],
          "cwd": "/path/to/knowledge_nexus"
        }
      }
    }
"""

from __future__ import annotations

import json
import logging

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight test envs
    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self) -> None:
            raise RuntimeError("mcp package is not installed")

from nexus.graph.neo4j_store import Neo4jGraphStore
from nexus.knowledge_os.application.services import (
    CandidateExtractionService,
    CandidateReviewService,
    EvidenceService,
    GraphCommitService,
)
from nexus.knowledge_os.domain.models import CandidateEdit, CandidateExtractionRequest
from nexus.knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from nexus.repositories.postgres import PostgresRepository
from nexus.settings import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

settings = Settings.from_env()

_neo4j: Neo4jGraphStore | None = None
_repo: PostgresRepository | None = None
_knowledge_os_store = InMemoryKnowledgeOSStore()


def _get_neo4j() -> Neo4jGraphStore:
    global _neo4j
    if _neo4j is None:
        _neo4j = Neo4jGraphStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
    return _neo4j


def _get_repo() -> PostgresRepository:
    global _repo
    if _repo is None:
        _repo = PostgresRepository(
            database_url=settings.database_url,
            tenant_id="default",
        )
    return _repo


mcp = FastMCP("knowledge-nexus")

# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------

def _node_to_dict(node) -> dict:
    return {
        "id": node.id,
        "uri": node.uri,
        "label": node.label,
        "summary": node.summary,
    }


def _doc_to_dict(doc) -> dict:
    return {
        "uri": doc.uri,
        "summary": doc.summary,
        "tags": doc.tags,
        "entities": doc.entities,
        "chunk_count": len(doc.chunks),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_documents() -> str:
    """List all processed documents with their summaries and tags.

    Returns a JSON array of {uri, summary, tags, entities, chunk_count}.
    Use this to discover what knowledge has been ingested.
    """
    docs = _get_repo().list_documents()
    return json.dumps([_doc_to_dict(d) for d in docs], ensure_ascii=False, indent=2)


@mcp.tool()
def get_document(uri: str) -> str:
    """Get full metadata for a specific document by its Cloudreve URI.

    Args:
        uri: The cloudreve:// URI of the document (e.g. cloudreve://my/report.pdf)

    Returns JSON with summary, tags, entities list, and chunk count.
    """
    doc = _get_repo().get_document(uri)
    if doc is None:
        return json.dumps({"error": f"Document not found: {uri}"})
    return json.dumps(_doc_to_dict(doc), ensure_ascii=False, indent=2)


@mcp.tool()
def search_entities(query: str) -> str:
    """Search the knowledge graph for entities matching a keyword.

    Searches all graph nodes (people, organizations, methods, concepts, etc.)
    by label. Also matches document nodes if the filename contains the keyword.

    Args:
        query: Keyword to search for (case-insensitive, partial match)

    Returns JSON array of matching nodes with id, label, and summary.
    """
    nodes = _get_neo4j().search_nodes(query, limit=20)
    return json.dumps([_node_to_dict(n) for n in nodes], ensure_ascii=False, indent=2)


@mcp.tool()
def get_document_graph(uri: str) -> str:
    """Get the knowledge graph for a specific document.

    Returns all entities extracted from the document and their relationships.

    Args:
        uri: The cloudreve:// URI of the document

    Returns JSON with nodes (entities) and edges (relations) arrays.
    """
    result = _get_neo4j().get_document_subgraph(uri)
    return json.dumps({
        "nodes": [_node_to_dict(n) for n in result.nodes],
        "edges": [
            {"source": e.source, "target": e.target, "relation": e.relation}
            for e in result.edges
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def find_documents_by_tag(tag: str) -> str:
    """Find documents that contain a specific tag.

    Args:
        tag: The tag to search for (case-insensitive, partial match)

    Returns JSON array of matching documents with uri, summary, and tags.
    """
    docs = _get_repo().list_documents()
    tag_lower = tag.lower()
    matched = [d for d in docs if any(tag_lower in t.lower() for t in d.tags)]
    return json.dumps(
        [{"uri": d.uri, "summary": d.summary, "tags": d.tags} for d in matched],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def run_candidate_extraction(
    uri: str,
    instructions: str | None = None,
    requested_by: str = "pi-agent",
    candidate_entities_json: str = "[]",
    candidate_relations_json: str = "[]",
    template_ids_json: str = "[]",
    parent_batch_id: str | None = None,
) -> str:
    """Create a candidate extraction batch without committing it to the graph.

    Args:
        uri: Source Cloudreve URI.
        instructions: Optional extraction/revision guidance.
        requested_by: Actor label for audit.
        candidate_entities_json: JSON array of candidate entity dicts.
        candidate_relations_json: JSON array of candidate relation dicts.
        template_ids_json: JSON array of template ids used.
        parent_batch_id: Optional previous batch id when regenerating from feedback.
    """
    service = CandidateExtractionService(_knowledge_os_store)
    batch = service.run(
        CandidateExtractionRequest(
            uri=uri,
            requested_by=requested_by,
            instructions=instructions,
            parent_batch_id=parent_batch_id,
            candidate_entities=_json_array(candidate_entities_json),
            candidate_relations=_json_array(candidate_relations_json),
            template_ids=[str(item) for item in _json_array(template_ids_json)],
        )
    )
    return json.dumps(
        {
            **service.describe_batch(batch.id),
            "next_actions": ["update_candidate_items", "preview_graph_changes", "commit_candidate_batch"],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def get_candidate_batch(batch_id: str) -> str:
    """Return candidate ontology and graph items for a batch."""
    try:
        result = CandidateExtractionService(_knowledge_os_store).describe_batch(batch_id)
    except KeyError as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def update_candidate_items(batch_id: str, edits_json: str) -> str:
    """Apply review edits to candidate graph items.

    Args:
        batch_id: Candidate batch id.
        edits_json: JSON array of {item_id, status?, payload?, review_note?}.
    """
    try:
        edits = [CandidateEdit(**item) for item in _json_array(edits_json)]
        updated = CandidateReviewService(_knowledge_os_store).apply_edits(batch_id, edits)
        result = {
            "batch_id": batch_id,
            "updated": [item.model_dump(mode="json") for item in updated],
            "next_actions": ["preview_graph_changes", "commit_candidate_batch"],
        }
    except (KeyError, ValueError) as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def preview_graph_changes(batch_id: str) -> str:
    """Preview graph diff for accepted candidate items."""
    try:
        result = GraphCommitService(_knowledge_os_store, repository=_get_repo()).preview(batch_id).model_dump(mode="json")
    except KeyError as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def commit_candidate_batch(batch_id: str) -> str:
    """Commit accepted candidate items into the controlled knowledge store."""
    try:
        result = GraphCommitService(_knowledge_os_store, repository=_get_repo()).commit(batch_id).model_dump(mode="json")
    except KeyError as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def explain_graph_evidence(node_or_edge_id: str) -> str:
    """Explain evidence records supporting a committed graph node or edge."""
    result = EvidenceService(_knowledge_os_store, repository=_get_repo()).explain(node_or_edge_id)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def ask_knowledge_graph(question: str, include_candidates: bool = False) -> str:
    """Answer by summarizing available committed documents and optional candidates."""
    docs = [_doc_to_dict(doc) for doc in _get_repo().list_documents()]
    payload = {"question": question, "documents": docs}
    if include_candidates:
        payload["candidate_batches"] = [
            {
                "batch": batch.model_dump(mode="json"),
                "items": [
                    item.model_dump(mode="json")
                    for item in _knowledge_os_store.list_candidate_graph_items(batch.id)
                ],
            }
            for batch in _knowledge_os_store.list_batches()
        ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def mark_source_deleted(uri: str) -> str:
    """Mark a source document deleted and stale its evidence without hard purge."""
    result = EvidenceService(_knowledge_os_store, repository=_get_repo()).mark_source_deleted(uri)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def purge_knowledge(uri: str, mode: str = "knowledge") -> str:
    """Explicitly purge knowledge evidence for a source URI."""
    result = EvidenceService(_knowledge_os_store, repository=_get_repo()).purge(uri, mode=mode)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _json_array(payload: str) -> list:
    try:
        value = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON array: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
