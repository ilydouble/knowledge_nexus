"""Knowledge OS MCP Server.

Exposes Knowledge OS candidate batches and the Neo4j knowledge graph as MCP
tools so that Pi-Agent (and any MCP-capable agent) can orchestrate the full
extract → review → commit workflow.

Usage:
    conda run -n nexus python -m apps.mcp.server

Claude Code / Pi-Agent ~/.claude/claude_desktop_config.json entry:
    {
      "mcpServers": {
        "knowledge-os": {
          "command": "/opt/miniconda3/envs/nexus/bin/python",
          "args": ["-m", "apps.mcp.server"],
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

from apps.api.factory import build_knowledge_os_store, build_repository
from core.graph.neo4j_store import Neo4jGraphStore
from knowledge_os.interfaces.mcp import register_knowledge_os_tools
from core.settings import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap — use the same store resolution as the API so Pi-Agent sees
# candidate batches created through REST or MCP.
# ---------------------------------------------------------------------------

settings = Settings.from_env()

_repo = build_repository(settings)
_knowledge_os_store = build_knowledge_os_store(settings, _repo)

_neo4j: Neo4jGraphStore | None = None


def _get_neo4j() -> Neo4jGraphStore:
    global _neo4j
    if _neo4j is None:
        _neo4j = Neo4jGraphStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
    return _neo4j


def _get_repo():
    return _repo


mcp = FastMCP("knowledge-os")

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


# ---------------------------------------------------------------------------
# Neo4j graph query tools (complement to Knowledge OS candidate tools)
# ---------------------------------------------------------------------------

@mcp.tool()
def search_entities(query: str) -> str:
    """Search committed graph nodes by keyword.

    Args:
        query: Keyword to search for (case-insensitive, partial match).

    Returns JSON array of matching nodes with id, uri, label, summary.
    Use ask_knowledge_graph for natural-language QA over the same graph.
    """
    nodes = _get_neo4j().search_nodes(query, limit=20)
    return json.dumps([_node_to_dict(n) for n in nodes], ensure_ascii=False, indent=2)


@mcp.tool()
def get_document_graph(uri: str) -> str:
    """Get all committed graph nodes and edges for a source document URI.

    Args:
        uri: The cloudreve:// URI of the source document.

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
delete_graph_nodes = _knowledge_os_tools["delete_graph_nodes"]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
