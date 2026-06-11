"""Agent3 — Graph Q&A Agent.

Answers natural-language questions by querying Neo4j (graph traversal)
and Milvus (semantic vector search).  Designed for direct use in API
endpoints or CLI without any classification step.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from strands import Agent, tool

from core.agents._model import build_model
from core.models import KnowledgeLayer
from core.settings import Settings

if TYPE_CHECKING:
    from core.graph.neo4j_store import Neo4jGraphStore
    from core.services.embedding import BigModelEmbeddingService
    from core.vector.milvus_store import MilvusVectorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a knowledge graph assistant for a document intelligence system.
You have access to a Neo4j graph of extracted entities/relations and a
Milvus vector store of document text chunks.

Strategy:
1. Use search_entities() for keyword-based entity lookup.
2. Use get_entity_neighborhood() to explore relationships around a node.
3. Use get_document_graph() when you need the full context of a document.
4. Use vector_search() for semantic similarity when entity lookup fails.
5. Synthesize findings into a clear, cited answer.

Always cite which nodes/documents support your answer.
"""


def create_graph_qa_agent(
    neo4j_store: Neo4jGraphStore,
    milvus_store: MilvusVectorStore,
    embedding_service: BigModelEmbeddingService,
    settings: Settings | None = None,
) -> Agent:
    """Return a configured Graph Q&A Agent with injected data stores."""
    model = build_model(settings)

    @tool
    def search_entities(keyword: str, limit: int = 10) -> str:
        """Search entities in the knowledge graph by label keyword.

        Args:
            keyword: Text to search for in entity labels.
            limit: Maximum number of results (default 10).
        """
        nodes = neo4j_store.search_nodes(keyword, limit=min(limit, 30))
        return json.dumps(
            [{"id": n.id, "label": n.label, "uri": n.uri, "summary": n.summary} for n in nodes],
            ensure_ascii=False,
        )

    @tool
    def get_entity_neighborhood(uri: str) -> str:
        """Get all entities and relations connected to a given node URI.

        Args:
            uri: The URI of the node (e.g. 'cloudreve://path/to/doc.pdf').
        """
        result = neo4j_store.neighborhood(
            uri, layers=[KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3]
        )
        return json.dumps(
            {
                "nodes": [{"id": n.id, "label": n.label, "summary": n.summary} for n in result.nodes],
                "edges": [{"source": e.source, "target": e.target, "relation": e.relation} for e in result.edges],
            },
            ensure_ascii=False,
        )

    @tool
    def get_document_graph(doc_uri: str) -> str:
        """Get the full knowledge subgraph extracted from a specific document.

        Args:
            doc_uri: The document URI (e.g. 'cloudreve://path/to/doc.pdf').
        """
        result = neo4j_store.get_document_subgraph(doc_uri)
        return json.dumps(
            {
                "nodes": [{"id": n.id, "label": n.label, "summary": n.summary} for n in result.nodes],
                "edges": [{"source": e.source, "target": e.target, "relation": e.relation} for e in result.edges],
            },
            ensure_ascii=False,
        )

    @tool
    def vector_search(query: str, limit: int = 5) -> str:
        """Semantic similarity search over document text chunks.

        Args:
            query: Natural-language query to search for.
            limit: Number of chunks to return (default 5).
        """
        if milvus_store is None:
            return json.dumps({"error": "Vector store not configured"})
        vector = embedding_service.embed(query)
        chunks = milvus_store.search(vector, limit=min(limit, 20))
        return json.dumps(
            [{"uri": c.uri, "text": c.text[:400]} for c in chunks],
            ensure_ascii=False,
        )

    return Agent(
        model=model,
        tools=[search_entities, get_entity_neighborhood, get_document_graph, vector_search],
        system_prompt=_SYSTEM_PROMPT,
    )


def ask(question: str, agent: Agent) -> str:
    """Ask a question and return the agent's answer as a string."""
    try:
        result = agent(question)
        return str(result).strip()
    except Exception as exc:
        logger.error("Graph Q&A agent failed: %s", exc)
        return f"Error: {exc}"
