#!/usr/bin/env python3
"""Graph Fusion - Align and merge multiple knowledge graphs.

Supports node alignment, relation merging, conflict resolution, and
confidence scoring. Designed for scenarios where different sources extract
overlapping but inconsistent information.

Usage:
    python graph_fusion.py --action align --graph1 g1.json --graph2 g2.json --strategy fuzzy
    python graph_fusion.py --action merge --graph1 g1.json --graph2 g2.json --conflict resolve
    python graph_fusion.py --action align-and-merge --graph1 g1.json --graph2 g2.json --output merged.json
    python graph_fusion.py --action consolidate --input graph.json --strategy majority
"""

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_label(label: str) -> str:
    """Normalize a label for comparison."""
    return re.sub(r"\s+", " ", label.strip().lower())


def similarity(a: str, b: str) -> float:
    """Compute string similarity between two labels."""
    return difflib.SequenceMatcher(None, normalize_label(a), normalize_label(b)).ratio()


def find_matches(nodes1: list[dict], nodes2: list[dict], threshold: float = 0.8) -> list[tuple[str, str, float]]:
    """Find matching nodes between two graphs."""
    matches: list[tuple[str, str, float]] = []
    used2: set[str] = set()
    for n1 in nodes1:
        id1 = n1["id"]
        best_match = None
        best_score = 0.0
        for n2 in nodes2:
            id2 = n2["id"]
            if id2 in used2:
                continue
            score = similarity(n1.get("label", ""), n2.get("label", ""))
            # Boost if same type
            if n1.get("type") == n2.get("type"):
                score = min(1.0, score + 0.2)
            if score > best_score and score >= threshold:
                best_score = score
                best_match = id2
        if best_match:
            used2.add(best_match)
            matches.append((id1, best_match, best_score))
    return matches


def merge_attributes(attrs1: dict, attrs2: dict) -> dict:
    """Merge attributes from two node representations."""
    merged = dict(attrs1)
    for k, v in attrs2.items():
        if k not in merged:
            merged[k] = v
        elif isinstance(v, list) and isinstance(merged[k], list):
            merged[k] = list(set(merged[k] + v))
        elif v and v != merged[k]:
            # Keep both as array
            merged[k] = list(set([str(merged[k]), str(v)]))
    return merged


def action_align(args: argparse.Namespace) -> dict:
    """Align nodes between two graphs."""
    g1 = load_json(args.graph1)
    g2 = load_json(args.graph2)

    nodes1 = g1.get("nodes", [])
    nodes2 = g2.get("nodes", [])

    if args.strategy == "exact":
        # Exact label match (case-insensitive)
        labels1 = {normalize_label(n.get("label", "")): n["id"] for n in nodes1}
        labels2 = {normalize_label(n.get("label", "")): n["id"] for n in nodes2}
        matches = []
        for label, id1 in labels1.items():
            if label in labels2:
                matches.append((id1, labels2[label], 1.0))
    elif args.strategy == "fuzzy":
        threshold = args.threshold or 0.8
        matches = find_matches(nodes1, nodes2, threshold)
    else:
        # Type-based alignment
        by_type: dict[str, list[dict]] = {}
        for n in nodes2:
            by_type.setdefault(n.get("type", ""), []).append(n)
        matches = []
        for n1 in nodes1:
            t = n1.get("type", "")
            candidates = by_type.get(t, [])
            for n2 in candidates:
                if similarity(n1.get("label", ""), n2.get("label", "")) >= (args.threshold or 0.85):
                    matches.append((n1["id"], n2["id"], 0.85))
                    break

    result = {
        "match_count": len(matches),
        "matches": [{"node1": m[0], "node2": m[1], "similarity": round(m[2], 3)} for m in matches],
        "nodes1_count": len(nodes1),
        "nodes2_count": len(nodes2),
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def action_merge(args: argparse.Namespace) -> dict:
    """Merge two graphs with conflict resolution."""
    g1 = load_json(args.graph1)
    g2 = load_json(args.graph2)

    matches = find_matches(
        g1.get("nodes", []), g2.get("nodes", []),
        threshold=args.threshold or 0.8
    )
    match_map: dict[str, str] = {(m[0], m[1]): m[2] for m in matches}
    match_pairs = [(m[0], m[1]) for m in matches]

    # Merge nodes
    seen: dict[str, dict] = {}
    for n in g1.get("nodes", []) + g2.get("nodes", []):
        nid = n["id"]
        if nid in seen:
            continue
        # Check if this node has a match
        matched_id = None
        for a, b in match_pairs:
            if nid == a:
                matched_id = b
                break
            if nid == b:
                matched_id = a
                break

        if matched_id and matched_id in seen:
            # Merge into existing
            existing = seen[matched_id]
            for k, v in n.items():
                if k not in existing:
                    existing[k] = v
                elif isinstance(v, list) and isinstance(existing[k], list):
                    existing[k] = list(set(existing[k] + v))
                elif v and v != existing[k] and k not in ("id",):
                    existing[k] = list(set([str(existing[k]), str(v)]))
        else:
            seen[nid] = dict(n)

    # Merge edges (dedup by source, relation, target)
    edge_set: set[tuple[str, str, str]] = set()
    all_edges = []
    for e in g1.get("edges", []) + g2.get("edges", []):
        key = (e.get("source", ""), e.get("relation", ""), e.get("target", ""))
        if key not in edge_set:
            edge_set.add(key)
            all_edges.append(e)

    merged = {"nodes": list(seen.values()), "edges": all_edges}

    if args.output:
        save_json(args.output, merged)
        print(f"Merged graph saved to {args.output}")

    return {"nodes": len(seen), "edges": len(all_edges), "original1": len(g1.get("nodes", [])), "original2": len(g2.get("nodes", [])), "graph": merged}


def action_consolidate(args: argparse.Namespace) -> dict:
    """Consolidate a graph by resolving conflicts in relation types.

    If multiple edges have same source-target but different relations,
    keep the most frequent one or merge them.
    """
    graph = load_json(args.input)
    edges = graph.get("edges", [])

    # Group by (source, target)
    groups: dict[tuple, list[dict]] = {}
    for e in edges:
        key = (e.get("source"), e.get("target"))
        groups.setdefault(key, []).append(e)

    resolved = []
    for (s, t), group_edges in groups.items():
        if len(group_edges) == 1:
            resolved.append(group_edges[0])
        else:
            # Find most common relation
            relation_counts = Counter(e.get("relation", "") for e in group_edges)
            if args.strategy == "majority":
                best_rel = relation_counts.most_common(1)[0][0]
                resolved.append({
                    "source": s, "target": t, "relation": best_rel,
                    "merged_relations": list(relation_counts.keys()),
                    "edge_count": len(group_edges),
                })
            else:
                for e in group_edges:
                    resolved.append(dict(e))

    consolidated = {"nodes": graph.get("nodes", []), "edges": resolved}
    dedup_count = len(edges) - len(resolved)

    if args.output:
        save_json(args.output, consolidated)
        print(f"Consolidated graph saved to {args.output} ({dedup_count} conflicts resolved)")

    return {"original_edges": len(edges), "consolidated_edges": len(resolved), "conflicts_resolved": dedup_count, "graph": consolidated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph Fusion - Align and merge knowledge graphs")
    parser.add_argument("--action", required=True, choices=["align", "merge", "align-and-merge", "consolidate"],
                        help="Action to perform")
    parser.add_argument("--graph1", help="First graph JSON file")
    parser.add_argument("--graph2", help="Second graph JSON file")
    parser.add_argument("--input", help="Input graph file (for consolidate)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--strategy", default="fuzzy", choices=["exact", "fuzzy", "type", "majority"],
                        help="Matching/consolidation strategy")
    parser.add_argument("--threshold", type=float, default=0.8, help="Similarity threshold for matching")
    parser.add_argument("--conflict", default="resolve", help="Conflict resolution strategy")
    args = parser.parse_args()

    if args.action == "align":
        action_align(args)
    elif args.action == "merge":
        action_merge(args)
    elif args.action == "align-and-merge":
        if not args.graph1 or not args.graph2:
            print("Error: --graph1 and --graph2 required for align-and-merge", file=sys.stderr)
            sys.exit(1)
        action_merge(args)
    elif args.action == "consolidate":
        if not args.input:
            print("Error: --input required for consolidate", file=sys.stderr)
            sys.exit(1)
        action_consolidate(args)


if __name__ == "__main__":
    main()
