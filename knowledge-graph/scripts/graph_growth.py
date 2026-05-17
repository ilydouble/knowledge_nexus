#!/usr/bin/env python3
"""Dynamic Graph Growth Engine - Incrementally extend and evolve a knowledge graph.

Supports iterative extraction, growth tracking, emerging pattern detection,
and graph versioning for long-running knowledge accumulation pipelines.

Usage:
    python graph_growth.py --action add --input graph.json --nodes new_nodes.json --edges new_edges.json
    python graph_growth.py --action evolve --input graph.json --prompt "Add entities about machine learning"
    python graph_growth.py --action detect-emerging --input graph.json --top-n 5
    python graph_growth.py --action version --input graph.json --version v1.1 --message "Added AI entities"
    python graph_growth.py --action compare --graph1 graph_v1.json --graph2 graph_v2.json
    python graph_growth.py --action hub-detection --input graph.json --top-n 10
"""

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_id(prefix: str = "node") -> str:
    """Generate a unique node ID."""
    short = uuid.uuid4().hex[:8]
    return f"{prefix}_{short}"


def action_add(args: argparse.Namespace) -> dict:
    """Add new nodes and edges to an existing graph."""
    graph = load_json(args.input)
    existing_nodes: dict[str, dict] = {}
    for n in graph.get("nodes", []):
        existing_nodes[n["id"]] = n

    existing_edges: set[tuple[str, str, str]] = set()
    for e in graph.get("edges", []):
        existing_edges.add((e.get("source", ""), e.get("relation", ""), e.get("target", "")))

    new_node_count = 0
    new_edge_count = 0
    added_ids: list[str] = []
    added_edges: list[dict] = []

    # Add nodes
    if args.nodes:
        new_nodes = load_json(args.nodes).get("nodes", [])
        for n in new_nodes:
            nid = n.get("id")
            if not nid:
                nid = generate_id()
                n["id"] = nid
            added_ids.append(nid)
            if nid not in existing_nodes:
                existing_nodes[nid] = n
                new_node_count += 1
            else:
                # Merge attributes
                existing = existing_nodes[nid]
                for k, v in n.items():
                    if k not in existing:
                        existing[k] = v
                    elif isinstance(v, list) and isinstance(existing[k], list):
                        existing[k] = list(set(existing[k] + v))
                    elif v and v != existing[k]:
                        existing[k] = list(set([str(existing[k]), str(v)]))

    # Add edges
    if args.edges:
        new_edges = load_json(args.edges).get("edges", [])
        for e in new_edges:
            key = (e.get("source"), e.get("relation"), e.get("target"))
            if key not in existing_edges:
                existing_edges.add(key)
                added_edges.append(e)
                new_edge_count += 1

    graph["nodes"] = list(existing_nodes.values())
    graph["edges"] = graph.get("edges", []) + added_edges
    graph.setdefault("history", []).append({
        "action": "add",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "new_nodes": new_node_count,
        "new_edges": new_edge_count,
    })

    if args.output:
        save_json(args.output, graph)
        print(f"Graph updated: +{new_node_count} nodes, +{new_edge_count} edges -> {args.output}")

    return {
        "new_nodes": new_node_count,
        "new_edges": new_edge_count,
        "total_nodes": len(graph["nodes"]),
        "total_edges": len(graph["edges"]),
        "added_ids": added_ids,
    }


def action_evolve(args: argparse.Namespace) -> dict:
    """Generate an evolution prompt for LLM-driven graph expansion.

    The actual LLM extraction is done via deer-flow agent tools. This script
    prepares the evolution strategy and tracks graph state.
    """
    graph = load_json(args.input)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    # Analyze current graph to suggest growth areas
    node_types = Counter(n.get("type", "Unknown") for n in nodes)
    relation_types = Counter(e.get("relation", "Unknown") for e in edges)

    # Find low-degree nodes (could use more connections)
    degree: dict[str, int] = Counter()
    for e in edges:
        degree[e.get("source", "")] += 1
        degree[e.get("target", "")] += 1

    isolated_nodes = [n["id"] for n in nodes if n["id"] not in degree]
    low_degree_nodes = [(nid, deg) for nid, deg in degree.items() if deg <= 1]

    # Find underrepresented types
    type_counts = dict(node_types)
    suggested_types = []

    evolution_strategy = {
        "current_stats": {"nodes": len(nodes), "edges": len(edges)},
        "isolated_nodes_count": len(isolated_nodes),
        "low_degree_nodes": low_degree_nodes[:20],
        "suggested_expansion": [],
        "prompt_hint": args.prompt or "",
    }

    if args.prompt:
        evolution_strategy["suggested_expansion"].append({
            "action": "extract",
            "domain": args.prompt,
            "priority": "high",
        })

    # Add type-based expansion suggestions
    for t, c in type_counts.items():
        if c < 5:
            evolution_strategy["suggested_expansion"].append({
                "action": "expand_type",
                "type": t,
                "current_count": c,
                "target_count": c * 2 + 3,
            })

    evolution_strategy["history"] = graph.get("history", []) + [{
        "action": "evolve",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": args.prompt,
    }]

    return evolution_strategy


def action_detect_emerging(args: argparse.Namespace) -> dict:
    """Detect emerging patterns - high-degree nodes (hubs) and new relation types."""
    graph = load_json(args.input)
    edges = graph.get("edges", [])
    nodes = graph.get("nodes", [])

    # Node centrality
    in_degree: dict[str, int] = Counter()
    out_degree: dict[str, int] = Counter()
    for e in edges:
        in_degree[e.get("target", "")] += 1
        out_degree[e.get("source", "")] += 1

    total_degree = in_degree + out_degree
    hubs = total_degree.most_common(args.top_n or 10)

    # Emerging relations (relations with few but growing edges)
    relation_counts = Counter(e.get("relation", "") for e in edges)
    relation_edges: dict[str, list] = {}
    for e in edges:
        r = e.get("relation", "")
        relation_edges.setdefault(r, []).append(e)

    emerging_relations = [
        {"relation": r, "count": c, "edges": len(edges_list)}
        for r, c in relation_counts.most_common()
        for edges_list in [relation_edges[r]]
        if c <= 3  # Low count = potentially new/emerging
    ]

    # Detect new node types (types with few nodes)
    type_counts = Counter(n.get("type", "") for n in nodes)
    new_types = [
        {"type": t, "count": c}
        for t, c in type_counts.items()
        if c <= 3 and t
    ]

    result = {
        "hubs": [{"id": h[0], "degree": h[1]} for h in hubs],
        "emerging_relations": emerging_relations,
        "new_types": new_types,
    }

    if args.output:
        save_json(args.output, result)
        print(f"Emerging patterns saved to {args.output}")

    return result


def action_version(args: argparse.Namespace) -> dict:
    """Create a version snapshot of the graph."""
    graph = load_json(args.input)

    version = {
        "version": args.version,
        "message": args.message or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "graph": graph,
    }

    output_path = args.output or f"graph_{args.version}.json"
    save_json(output_path, version)
    print(f"Version {args.version} saved to {output_path}")

    return version


def action_compare(args: argparse.Namespace) -> dict:
    """Compare two graph versions."""
    g1 = load_json(args.graph1)
    g2 = load_json(args.graph2)

    nodes1 = {n["id"]: n for n in g1.get("nodes", [])}
    nodes2 = {n["id"]: n for n in g2.get("nodes", [])}

    added_nodes = set(nodes2.keys()) - set(nodes1.keys())
    removed_nodes = set(nodes1.keys()) - set(nodes2.keys())
    common_nodes = set(nodes1.keys()) & set(nodes2.keys())

    # Nodes with changed attributes
    changed_nodes = []
    for nid in common_nodes:
        diff = {}
        n1 = nodes1[nid]
        n2 = nodes2[nid]
        all_keys = set(n1.keys()) | set(n2.keys())
        for k in all_keys:
            if k == "id":
                continue
            v1 = n1.get(k)
            v2 = n2.get(k)
            if v1 != v2:
                diff[k] = {"old": v1, "new": v2}
        if diff:
            changed_nodes.append({"id": nid, "changes": diff})

    edges1 = {(e.get("source"), e.get("relation"), e.get("target")) for e in g1.get("edges", [])}
    edges2 = {(e.get("source"), e.get("relation"), e.get("target")) for e in g2.get("edges", [])}

    added_edges = edges2 - edges1
    removed_edges = edges1 - edges2

    result = {
        "node_delta": {"added": len(added_nodes), "removed": len(removed_nodes), "changed": len(changed_nodes)},
        "edge_delta": {"added": len(added_edges), "removed": len(removed_edges)},
        "added_node_ids": list(added_nodes),
        "removed_node_ids": list(removed_nodes),
        "changed_nodes": changed_nodes[:50],  # Limit output
        "added_edges": list(added_edges)[:100],
        "removed_edges": list(removed_edges)[:100],
    }

    if args.output:
        save_json(args.output, result)

    return result


def action_hub_detection(args: argparse.Namespace) -> dict:
    """Identify hub nodes and community structure hints."""
    graph = load_json(args.input)
    edges = graph.get("edges", [])

    # Degree analysis
    degree: dict[str, dict] = {}
    for e in edges:
        s, t = e.get("source", ""), e.get("target", "")
        r = e.get("relation", "")
        for nid in (s, t):
            if nid not in degree:
                degree[nid] = {"in": 0, "out": 0, "total": 0, "relations": set()}
        degree[s]["out"] += 1
        degree[s]["relations"].add(r)
        degree[t]["in"] += 1
        degree[t]["relations"].add(r)

    for nid in degree:
        degree[nid]["total"] = degree[nid]["in"] + degree[nid]["out"]

    # Sort and top-N
    sorted_hubs = sorted(degree.items(), key=lambda x: -x[1]["total"])
    top_hubs = [
        {
            "id": nid,
            "total_degree": d["total"],
            "in_degree": d["in"],
            "out_degree": d["out"],
            "relations": sorted(d["relations"]),
        }
        for nid, d in sorted_hubs[:args.top_n or 10]
    ]

    result = {
        "hub_count": len(degree),
        "top_hubs": top_hubs,
    }

    if args.output:
        save_json(args.output, result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynamic Graph Growth Engine")
    parser.add_argument("--action", required=True, choices=["add", "evolve", "detect-emerging", "version", "compare", "hub-detection"],
                        help="Action to perform")
    parser.add_argument("--input", help="Input graph JSON file")
    parser.add_argument("--input2", help="Second input file")
    parser.add_argument("--graph1", help="First graph file")
    parser.add_argument("--graph2", help="Second graph file")
    parser.add_argument("--nodes", help="New nodes JSON file")
    parser.add_argument("--edges", help="New edges JSON file")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--version", type=str, help="Version string")
    parser.add_argument("--message", type=str, help="Version message")
    parser.add_argument("--prompt", type=str, help="Evolution prompt for LLM")
    parser.add_argument("--top-n", type=int, default=10, help="Top N results")
    args = parser.parse_args()

    if args.action == "add":
        result = action_add(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "evolve":
        if not args.input:
            print("Error: --input required for evolve", file=sys.stderr)
            sys.exit(1)
        result = action_evolve(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "detect-emerging":
        if not args.input:
            print("Error: --input required for detect-emerging", file=sys.stderr)
            sys.exit(1)
        result = action_detect_emerging(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "version":
        result = action_version(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "compare":
        if not args.graph1 or not args.graph2:
            print("Error: --graph1 and --graph2 required for compare", file=sys.stderr)
            sys.exit(1)
        result = action_compare(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "hub-detection":
        if not args.input:
            print("Error: --input required for hub-detection", file=sys.stderr)
            sys.exit(1)
        result = action_hub_detection(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
