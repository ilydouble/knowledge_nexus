"""GovernanceService — Phase 5 Admin governance layer.

Provides:
- dashboard()       : aggregate stats across batches, items, evidence
- list_batches()    : filterable batch listing
- bulk_accept()     : accept all pending items in a batch
- bulk_reject()     : reject all pending items in a batch
- stale_report()    : list stale/purged evidence records across all sources
"""

from __future__ import annotations

from typing import Any

from knowledge_os.domain.models import CandidateGraphItem
from knowledge_os.infrastructure.store import KnowledgeOSStore


class GovernanceService:
    """Admin-facing governance operations for the Knowledge OS."""

    def __init__(self, store: KnowledgeOSStore) -> None:
        self.store = store

    # ── Dashboard ────────────────────────────────────────────────────────────

    def dashboard(self) -> dict[str, Any]:
        """Return aggregate counts across batches, graph items and evidence."""
        batches = self.store.list_batches()

        batch_by_status: dict[str, int] = {}
        for b in batches:
            batch_by_status[b.status] = batch_by_status.get(b.status, 0) + 1

        items_by_status: dict[str, int] = {}
        total_nodes = 0
        total_edges = 0
        for b in batches:
            for item in self.store.list_candidate_graph_items(b.id):
                items_by_status[item.status] = items_by_status.get(item.status, 0) + 1
                if item.kind == "node":
                    total_nodes += 1
                else:
                    total_edges += 1

        all_evidence = self.store.list_graph_evidence()
        evidence_by_status: dict[str, int] = {}
        for ev in all_evidence:
            evidence_by_status[ev.status] = evidence_by_status.get(ev.status, 0) + 1

        stale_count = evidence_by_status.get("stale", 0)
        purged_count = evidence_by_status.get("purged", 0)

        return {
            "batch_total": len(batches),
            "batch_by_status": batch_by_status,
            "graph_items": {
                "total": total_nodes + total_edges,
                "nodes": total_nodes,
                "edges": total_edges,
                "by_status": items_by_status,
            },
            "evidence": {
                "total": len(all_evidence),
                "by_status": evidence_by_status,
                "stale": stale_count,
                "purged": purged_count,
                "healthy": len(all_evidence) - stale_count - purged_count,
            },
            "alerts": self._compute_alerts(stale_count, batch_by_status),
        }

    @staticmethod
    def _compute_alerts(stale_count: int, batch_by_status: dict[str, int]) -> list[str]:
        alerts: list[str] = []
        if stale_count > 0:
            alerts.append(f"{stale_count} stale evidence record(s) — consider purge or re-extraction.")
        pending = batch_by_status.get("pending", 0) + batch_by_status.get("reviewing", 0)
        if pending > 5:
            alerts.append(f"{pending} candidate batch(es) awaiting review.")
        return alerts

    # ── Batch listing ────────────────────────────────────────────────────────

    def list_batches(
        self,
        status: str | None = None,
        source_uri: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List batches with optional filtering by status and/or source_uri."""
        batches = self.store.list_batches()
        if status:
            batches = [b for b in batches if b.status == status]
        if source_uri:
            batches = [b for b in batches if b.source_uri == source_uri]
        batches = batches[:limit]

        rows = []
        for b in batches:
            items = self.store.list_candidate_graph_items(b.id)
            rows.append({
                **b.model_dump(mode="json"),
                "item_counts": _count_items(items),
            })
        return {"total": len(rows), "batches": rows}

    # ── Bulk review ──────────────────────────────────────────────────────────

    def bulk_accept(self, batch_id: str) -> dict[str, Any]:
        """Set all pending candidate items in a batch to 'accepted'."""
        return self._bulk_set_status(batch_id, target="accepted", eligible={"candidate", "pending", "reviewing"})

    def bulk_reject(self, batch_id: str) -> dict[str, Any]:
        """Set all pending candidate items in a batch to 'rejected'."""
        return self._bulk_set_status(batch_id, target="rejected", eligible={"candidate", "pending", "reviewing"})

    def _bulk_set_status(
        self, batch_id: str, *, target: str, eligible: set[str]
    ) -> dict[str, Any]:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise KeyError(f"candidate batch not found: {batch_id}")
        if batch.status == "committed":
            raise ValueError("committed batches cannot be bulk-reviewed")

        updated = 0
        skipped = 0
        for item in self.store.list_candidate_graph_items(batch_id):
            if item.status in eligible:
                self.store.update_candidate_graph_item(item.model_copy(update={"status": target}))
                updated += 1
            else:
                skipped += 1
        return {
            "batch_id": batch_id,
            "action": target,
            "updated": updated,
            "skipped": skipped,
            "next_actions": (
                ["preview_graph_changes", "commit_candidate_batch"]
                if target == "accepted"
                else []
            ),
        }

    # ── Stale evidence report ────────────────────────────────────────────────

    def stale_report(self) -> dict[str, Any]:
        """Return all stale or purged evidence grouped by source_uri."""
        all_ev = self.store.list_graph_evidence()
        stale = [e for e in all_ev if e.status in ("stale", "purged")]

        by_uri: dict[str, list[dict[str, Any]]] = {}
        for ev in stale:
            uri = ev.source_uri or "unknown"
            by_uri.setdefault(uri, []).append({
                "graph_item_id": ev.graph_item_id,
                "status": ev.status,
                "batch_id": ev.batch_id,
                "evidence_text": (ev.evidence_text or "")[:200],
                "confidence": ev.confidence,
            })

        return {
            "stale_total": len(stale),
            "sources_affected": len(by_uri),
            "by_source_uri": by_uri,
            "recommendation": (
                "Call purge_knowledge(uri) for each affected source to remove stale knowledge."
                if stale else "No stale evidence found."
            ),
        }


def _count_items(items: list[CandidateGraphItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts
