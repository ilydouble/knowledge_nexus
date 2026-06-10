"""Agent4 — Graph Completion Agent.

Analyzes the knowledge graph for structural gaps: isolated nodes,
missing cross-document links, and weak relationships. Produces a
report with actionable link suggestions.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from strands import Agent, tool

from nexus.agents._model import build_model
from nexus.models import KnowledgeLayer
from nexus.settings import Settings

if TYPE_CHECKING:
    from nexus.graph.neo4j_store import Neo4jGraphStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a knowledge graph quality analyst.
Your goal: identify structural gaps in the graph and suggest missing links.

Steps:
1. Call get_graph_stats() to understand the overall graph health.
2. Call list_document_nodes() to see all processed documents.
3. Call list_entity_nodes(keyword) to explore entity populations by domain.
4. Call get_entity_neighborhood(uri) to check connectivity of suspect nodes.
5. Produce a structured report with:
   - Summary of graph health (node/edge counts, isolated nodes)
   - List of suggested links: {source, target, suggested_relation, reason}
   - Recommended documents to re-process or enrich

Output JSON:
{
  "health": {"total_nodes": N, "total_edges": N, "isolated_nodes": N},
  "suggested_links": [{"source": "...", "target": "...", "relation": "...", "reason": "..."}],
  "recommendations": ["..."]
}
"""


def create_graph_completion_agent(
    neo4j_store: Neo4jGraphStore,
    settings: Settings | None = None,
) -> Agent:
    """Return a configured Graph Completion Agent."""
    model = build_model(settings)

    @tool
    def get_graph_stats() -> str:
        """Get high-level statistics about the knowledge graph health."""
        result = neo4j_store.full_graph()
        connected_ids = set()
        for e in result.edges:
            connected_ids.add(e.source)
            connected_ids.add(e.target)
        isolated = [n for n in result.nodes if n.id not in connected_ids]
        return json.dumps(
            {
                "total_nodes": len(result.nodes),
                "total_edges": len(result.edges),
                "isolated_node_count": len(isolated),
                "isolated_nodes": [
                    {"id": n.id, "label": n.label, "uri": n.uri} for n in isolated[:15]
                ],
            },
            ensure_ascii=False,
        )

    @tool
    def list_document_nodes(limit: int = 50) -> str:
        """List processed document nodes in the graph.

        Args:
            limit: Maximum number of documents to return (default 50).
        """
        nodes = neo4j_store.list_file_nodes(limit=min(limit, 200))
        return json.dumps(
            [{"id": n.id, "label": n.label, "uri": n.uri, "summary": (n.summary or "")[:200]} for n in nodes],
            ensure_ascii=False,
        )

    @tool
    def list_entity_nodes(keyword: str = "", limit: int = 30) -> str:
        """List entity nodes, optionally filtered by keyword.

        Args:
            keyword: Optional filter string (e.g. 'Company', 'Drug', '').
            limit: Maximum results (default 30).
        """
        nodes = neo4j_store.list_entity_nodes(keyword=keyword, limit=min(limit, 100))
        return json.dumps(
            [{"id": n.id, "label": n.label, "uri": n.uri} for n in nodes],
            ensure_ascii=False,
        )

    @tool
    def get_entity_neighborhood(uri: str) -> str:
        """Get connected entities and relations for a node to check connectivity.

        Args:
            uri: Node URI or entity URI to inspect.
        """
        result = neo4j_store.neighborhood(
            uri, layers=[KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3]
        )
        return json.dumps(
            {
                "node_count": len(result.nodes),
                "edge_count": len(result.edges),
                "edges": [
                    {"source": e.source, "target": e.target, "relation": e.relation}
                    for e in result.edges[:20]
                ],
            },
            ensure_ascii=False,
        )

    return Agent(
        model=model,
        tools=[get_graph_stats, list_document_nodes, list_entity_nodes, get_entity_neighborhood],
        system_prompt=_SYSTEM_PROMPT,
    )


def analyze_graph(agent: Agent) -> dict:
    """Run the graph completion agent and return the parsed report dict."""
    try:
        result = agent("Analyze the knowledge graph and produce a completion report.")
        text = str(result).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        return json.loads(text)
    except Exception as exc:
        logger.error("Graph completion agent failed: %s", exc)
        return {"error": str(exc)}
