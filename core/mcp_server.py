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

from core.graph.neo4j_store import Neo4jGraphStore
from knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from knowledge_os.interfaces.mcp import register_knowledge_os_tools
from core.repositories.postgres import PostgresRepository
from core.settings import Settings

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


from knowledge_os.application.extraction_pipeline import build_candidate_extraction_pipeline
_extraction_pipeline = build_candidate_extraction_pipeline(settings, _knowledge_os_store)

# Eagerly init Neo4j for Knowledge OS tools (graceful fallback on failure)
_neo4j_for_knowledge_os: Neo4jGraphStore | None = None
try:
    _neo4j_for_knowledge_os = _get_neo4j()
except Exception as _neo4j_exc:
    logger.warning("Knowledge OS: Neo4j unavailable at startup (%s); commit will warn.", _neo4j_exc)

_knowledge_os_tools = register_knowledge_os_tools(
    mcp,
    store=_knowledge_os_store,
    get_repository=_get_repo,
    extraction_pipeline=_extraction_pipeline,
    neo4j_store=_neo4j_for_knowledge_os,
)

run_candidate_extraction = _knowledge_os_tools["run_candidate_extraction"]
get_candidate_batch = _knowledge_os_tools["get_candidate_batch"]
update_candidate_items = _knowledge_os_tools["update_candidate_items"]
preview_graph_changes = _knowledge_os_tools["preview_graph_changes"]
commit_candidate_batch = _knowledge_os_tools["commit_candidate_batch"]
explain_graph_evidence = _knowledge_os_tools["explain_graph_evidence"]
ask_knowledge_graph = _knowledge_os_tools["ask_knowledge_graph"]
mark_source_deleted = _knowledge_os_tools["mark_source_deleted"]
purge_knowledge = _knowledge_os_tools["purge_knowledge"]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
