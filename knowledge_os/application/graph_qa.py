"""GraphQAService — Phase 4 knowledge graph Q&A.

Strategy (no LLM needed here — Pi-Agent / Claude synthesises the answer):
1. Extract keywords from the question (simple tokenisation).
2. Search Neo4j for entity nodes matching each keyword.
3. Retrieve 1-hop neighbourhood for the top-N entities.
4. Fetch graph_evidence records for those entities.
5. Optionally include candidate batches (include_candidates=True).
6. Return structured JSON context for Pi-Agent to synthesise an answer.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from knowledge_os.infrastructure.store import KnowledgeOSStore

if TYPE_CHECKING:
    from core.graph.neo4j_store import Neo4jGraphStore
    from core.models import KnowledgeLayer

# Chinese + ASCII stop-words to skip during keyword extraction
_STOP = frozenset(
    "的 了 是 在 和 与 或 对 有 将 被 由 为 以 从 到 该 这 那 其 一 二 三 "
    "的 a an the is are was were be been has have had do does did "
    "what which who how when where why can could would should".split()
)
_MAX_KEYWORDS = 5
_MAX_ENTITY_HITS = 6   # entities per keyword
_MAX_NEIGHBOURHOOD_NODES = 30


def _extract_keywords(question: str) -> list[str]:
    """Naively tokenise a question into candidate search keywords."""
    tokens = re.split(r"[\s,，。？?！!、；;：:「」【】()（）]+", question)
    seen: list[str] = []
    for token in tokens:
        t = token.strip().lower()
        if len(t) >= 2 and t not in _STOP and t not in seen:
            seen.append(t)
        if len(seen) >= _MAX_KEYWORDS:
            break
    return seen


class GraphQAService:
    """Retrieves structured graph context for a natural-language question."""

    def __init__(
        self,
        store: KnowledgeOSStore,
        neo4j_store: Neo4jGraphStore | None = None,
    ) -> None:
        self.store = store
        self.neo4j_store = neo4j_store

    def ask(self, question: str, *, include_candidates: bool = False) -> dict[str, Any]:
        keywords = _extract_keywords(question)
        entity_hits: dict[str, dict[str, Any]] = {}   # uri → node dict
        edges_seen: dict[str, dict[str, Any]] = {}     # edge id → edge dict
        evidence_map: dict[str, list[dict[str, Any]]] = {}  # graph_item_id → evidence list

        # ── Neo4j search ─────────────────────────────────────────────────────
        if self.neo4j_store is not None:
            from core.models import KnowledgeLayer
            all_layers = [KnowledgeLayer.L1, KnowledgeLayer.L2, KnowledgeLayer.L3]

            for kw in keywords:
                for node in self.neo4j_store.search_nodes(kw, limit=_MAX_ENTITY_HITS):
                    if node.uri and node.uri not in entity_hits:
                        entity_hits[node.uri] = {
                            "id": node.id,
                            "uri": node.uri,
                            "label": node.label,
                            "summary": node.summary,
                            "matched_keyword": kw,
                        }

            # 1-hop neighbourhood for each found entity
            neighbourhood_budget = _MAX_NEIGHBOURHOOD_NODES
            for uri in list(entity_hits.keys()):
                if neighbourhood_budget <= 0:
                    break
                try:
                    result = self.neo4j_store.neighborhood(uri, layers=all_layers)
                    for node in result.nodes:
                        if node.uri and node.uri not in entity_hits:
                            entity_hits[node.uri] = {
                                "id": node.id,
                                "uri": node.uri,
                                "label": node.label,
                                "summary": node.summary,
                                "matched_keyword": None,
                            }
                            neighbourhood_budget -= 1
                    for edge in result.edges:
                        if edge.id not in edges_seen:
                            edges_seen[edge.id] = {
                                "source": edge.source,
                                "target": edge.target,
                                "relation": edge.relation,
                                "source_file_uri": edge.source_file_uri,
                            }
                except Exception:
                    pass
        else:
            entity_hits = {}

        # ── Evidence retrieval ────────────────────────────────────────────────
        for node_info in entity_hits.values():
            node_id = node_info["id"]
            graph_item_id = f"node:{node_id}"
            ev_list = self.store.list_graph_evidence(graph_item_id=graph_item_id)
            if ev_list:
                evidence_map[graph_item_id] = [
                    {
                        "source_uri": e.source_uri,
                        "evidence_text": e.evidence_text,
                        "confidence": e.confidence,
                        "status": e.status,
                        "batch_id": e.batch_id,
                    }
                    for e in ev_list
                    if e.status not in ("stale", "purged")
                ]

        # ── Candidate batches (optional) ──────────────────────────────────────
        candidate_context: list[dict[str, Any]] = []
        if include_candidates:
            for batch in self.store.list_batches():
                if batch.status == "committed":
                    continue
                items = self.store.list_candidate_graph_items(batch.id)
                candidate_context.append({
                    "batch_id": batch.id,
                    "source_uri": batch.source_uri,
                    "status": batch.status,
                    "items": [
                        {"kind": i.kind, "payload": i.payload, "status": i.status}
                        for i in items
                        if i.status not in ("rejected",)
                    ],
                })

        return {
            "question": question,
            "keywords_used": keywords,
            "graph_available": self.neo4j_store is not None,
            "entities": list(entity_hits.values()),
            "relations": list(edges_seen.values()),
            "evidence": evidence_map,
            "candidate_context": candidate_context,
            "answer_hint": (
                "Use the entities, relations and evidence above to answer the question. "
                "Cite source_uri and evidence_text where available. "
                "Mark any knowledge from stale/purged evidence as potentially outdated."
            ),
        }
