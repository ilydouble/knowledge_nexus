#!/usr/bin/env python3
"""Graph Query Engine - Query, traverse and analyze a knowledge graph.

Supports path finding, subgraph extraction, pattern matching, and
graph analytics through a CLI interface. The full graph database query
capabilities are available via the graph store (Neo4j, NebulaGraph, etc.).

Usage:
    python graph_query.py --action nodes --type "Person" --input graph.json
    python graph_query.py --action neighbors --node "person_abc123" --depth 2 --input graph.json
    python graph_query.py --action path --source "person_abc123" --target "person_xyz789" --input graph.json
    python graph_query.py --action pattern --pattern "Person->DISCOVERED->Concept" --input graph.json
    python graph_query.py --action subgraph --seeds "node1,node2" --depth 2 --input graph.json
    python graph_query.py --action stats --input graph.json
    python graph_query.py --action export --format neo4j --input graph.json --output nodes.cypher
"""

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_adjacency(edges: list[dict]) -> dict[str, list[dict]]:
    """Build adjacency list from edges."""
    adj: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        s, t, r = e.get("source", ""), e.get("relation", ""), e.get("target", "")
        adj[s].append({"target": t, "relation": r, "edge": e})
    return adj


def build_undirected_adj(edges: list[dict]) -> dict[str, list[dict]]:
    """Build undirected adjacency list."""
    adj: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        s, t, r = e.get("source", ""), e.get("target", ""), e.get("relation", "")
        adj[s].append({"target": t, "relation": r, "direction": "out", "edge": e})
        adj[t].append({"target": s, "relation": r, "direction": "in", "edge": e})
    return adj


def action_nodes(args: argparse.Namespace) -> dict:
    """Get nodes matching criteria."""
    graph = load_json(args.input)
    nodes = graph.get("nodes", [])

    filtered = []
    for n in nodes:
        match = True
        if args.type and n.get("type") != args.type:
            match = False
        if args.label and args.label.lower() not in n.get("label", "").lower():
            match = False
        if match:
            filtered.append(n)

    return {"count": len(filtered), "nodes": filtered}


def action_neighbors(args: argparse.Namespace) -> dict:
    """Get neighbors of a node up to a given depth."""
    graph = load_json(args.input)
    edges = graph.get("edges", [])
    adj = build_undirected_adj(edges)

    target = args.node
    visited: set[str] = set()
    result_nodes: dict[str, dict] = {}
    result_edges: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(target, 0)])

    # First, add the target node itself
    for n in graph.get("nodes", []):
        if n["id"] == target:
            result_nodes[target] = n
            break

    while queue:
        current, depth = queue.popleft()
        if current in visited or depth > (args.depth or 1):
            continue
        visited.add(current)

        for neighbor in adj.get(current, []):
            nt = neighbor["target"]
            if nt not in visited:
                # Add edge
                edge = neighbor.get("edge", {})
                result_edges.append(edge)
                # Add neighbor node
                for n in graph.get("nodes", []):
                    if n["id"] == nt and nt not in result_nodes:
                        result_nodes[nt] = n
                        break
                queue.append((nt, depth + 1))

    return {
        "seed_node": target,
        "max_depth": args.depth or 1,
        "nodes": list(result_nodes.values()),
        "edges": result_edges,
        "node_count": len(result_nodes),
    }


def action_path(args: argparse.Namespace) -> dict:
    """Find shortest path between two nodes (BFS)."""
    graph = load_json(args.input)
    edges = graph.get("edges", [])
    adj = build_undirected_adj(edges)

    source = args.source
    target = args.target

    # BFS
    visited: set[str] = {source}
    queue: deque[tuple[str, list[str], list[dict]]] = deque([(source, [source], [])])
    found_path: list[str] = []
    found_edges: list[dict] = []

    while queue:
        current, path, path_edges = queue.popleft()
        if current == target:
            found_path = path
            found_edges = path_edges
            break
        for neighbor in adj.get(current, []):
            nt = neighbor["target"]
            if nt not in visited:
                visited.add(nt)
                queue.append((nt, path + [nt], path_edges + [neighbor.get("edge", {})]))

    if found_path:
        result = {"found": True, "path": found_path, "edges": found_edges, "length": len(found_path) - 1}
    else:
        result = {"found": False, "path": [], "edges": [], "length": -1}

    return result


def action_pattern(args: argparse.Namespace) -> dict:
    """Find all instances of a pattern in the graph.

    Pattern format: "Type1->Relation1->Type2" or "Type1->Relation1->Type2->Relation2->Type3"
    """
    graph = load_json(args.input)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    node_types: dict[str, dict] = {n["id"]: n for n in nodes}
    pattern_parts = [p.strip() for p in args.pattern.split("->")]

    if len(pattern_parts) == 2:
        # Simple: SRC_TYPE->RELATION
        src_type, rel = pattern_parts
        matches = []
        for e in edges:
            if e.get("relation") == rel:
                src = node_types.get(e.get("source", ""), {})
                if src.get("type") == src_type:
                    matches.append(e)
        return {"pattern": args.pattern, "matches": matches, "count": len(matches)}

    elif len(pattern_parts) == 4:
        # SRC_TYPE->REL1->DST_TYPE
        src_type, rel, dst_type = pattern_parts[0], pattern_parts[1], pattern_parts[2]
        matches = []
        for e in edges:
            if e.get("relation") == rel:
                src = node_types.get(e.get("source", ""), {})
                dst = node_types.get(e.get("target", ""), {})
                if src.get("type") == src_type and dst.get("type") == dst_type:
                    matches.append(e)
        return {"pattern": args.pattern, "matches": matches, "count": len(matches)}

    elif len(pattern_parts) == 6:
        # SRC_TYPE->REL1->MID_TYPE->REL2->DST_TYPE
        src_type, rel1, mid_type, rel2, dst_type = pattern_parts
        adj: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            adj[e.get("source", "")].append(e)

        matches = []
        for e1 in edges:
            if e1.get("relation") != rel1:
                continue
            src = node_types.get(e1.get("source", ""), {})
            if src.get("type") != src_type:
                continue
            mid = e1.get("target")
            for e2 in adj.get(mid, []):
                if e2.get("relation") != rel2:
                    continue
                dst = node_types.get(e2.get("target", ""), {})
                if dst.get("type") == dst_type:
                    matches.append({"path": [e1.get("source"), mid, e2.get("target")], "edges": [e1, e2]})
        return {"pattern": args.pattern, "matches": matches, "count": len(matches)}

    return {"error": f"Unsupported pattern format: {args.pattern}", "suggested": "TYPE1->REL->TYPE2"}


def action_subgraph(args: argparse.Namespace) -> dict:
    """Extract a subgraph centered on seed nodes."""
    graph = load_json(args.input)
    edges = graph.get("edges", [])
    adj = build_undirected_adj(edges)

    seeds = [s.strip() for s in args.seeds.split(",")]
    depth = args.depth or 1

    visited: set[str] = set(seeds)
    queue: deque[str] = deque(seeds)
    node_set: set[str] = set(seeds)

    while queue:
        current = queue.popleft()
        for neighbor in adj.get(current, []):
            nt = neighbor["target"]
            if nt not in visited and depth > 0:
                visited.add(nt)
                node_set.add(nt)
                queue.append(nt)

    # Filter nodes and edges
    sub_nodes = [n for n in graph.get("nodes", []) if n["id"] in node_set]
    sub_edges = [e for e in edges if e.get("source") in node_set and e.get("target") in node_set]

    return {"seed_count": len(seeds), "subgraph_nodes": len(sub_nodes), "subgraph_edges": len(sub_edges), "nodes": sub_nodes, "edges": sub_edges}


def action_export(args: argparse.Namespace) -> dict:
    """Export graph in various formats."""
    graph = load_json(args.input)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    fmt = args.format

    if fmt == "neo4j":
        # Cypher import statements
        lines = ["// Knowledge Graph Export", ""]
        # Create node constraints
        node_types = set(n.get("type", "") for n in nodes)
        for t in node_types:
            type_id = t.lower()
            lines.append(f"CREATE CONSTRAINT {type_id}_id IF NOT EXISTS FOR (n:{t}) REQUIRE n.id IS UNIQUE;")
        lines.append("")
        # Merge nodes
        for n in nodes:
            props = ", ".join(f"{k}: ${k}_{n['id']}" for k in n if k not in ("id",))
            lines.append(f"MERGE (n:{n['type']} {{id: '{n['id']}'}}) SET {props};")
        lines.append("")
        # Merge edges
        for e in edges:
            lines.append(f"MATCH (a {{id: '{e.get('source')}')}}, (b {{id: '{e.get('target')}')}}) CREATE (a)-[:{e.get('relation')}]->(b);")

        content = "\n".join(lines)
        if args.output:
            Path(args.output).write_text(content, encoding="utf-8")

        return {"format": fmt, "output": args.output or "stdout", "node_count": len(nodes), "edge_count": len(edges)}

    elif fmt == "json-ld":
        import hashlib
        graph_id = "urn:knowledge-graph:main"
        context = {
            "@context": {
                "@vocab": "http://example.org/kg/",
                "id": "@id",
                "type": "@type",
                "label": "rdfs:label",
                "description": "rdfs:comment",
            }
        }
        graph_data = {
            "@graph": []
        }
        for n in nodes:
            graph_data["@graph"].append({
                "@id": f"#{n['id']}",
                "id": n["id"],
                "type": n.get("type", ""),
                "label": n.get("label", ""),
                **{k: v for k, v in n.items() if k not in ("id", "type", "label")},
            })
        for e in edges:
            graph_data["@graph"].append({
                "@id": f"edge_{hashlib.md5(f\"{e['source']}_{e['relation']}_{e['target']}\".encode()).hexdigest()[:8]}",
                "type": "Relation",
                "source": e.get("source"),
                "relation": e.get("relation"),
                "target": e.get("target"),
            })

        output = {**context, **graph_data}
        if args.output:
            save_json(args.output, output)
            return {"format": fmt, "output": args.output}
        return {"format": fmt, "data": output}

    return {"error": f"Unsupported format: {fmt}"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph Query Engine")
    parser.add_argument("--action", required=True, choices=["nodes", "neighbors", "path", "pattern", "subgraph", "stats", "export"],
                        help="Action to perform")
    parser.add_argument("--input", required=True, help="Input graph JSON file")
    parser.add_argument("--type", help="Filter by node type")
    parser.add_argument("--label", help="Filter by label substring")
    parser.add_argument("--node", help="Target node ID")
    parser.add_argument("--source", help="Source node ID")
    parser.add_argument("--target", help="Target node ID")
    parser.add_argument("--pattern", help="Pattern string (TYPE->REL->TYPE)")
    parser.add_argument("--seeds", help="Comma-separated seed node IDs")
    parser.add_argument("--depth", type=int, help="Traversal depth")
    parser.add_argument("--format", choices=["neo4j", "json-ld"], help="Export format")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    if args.action == "nodes":
        result = action_nodes(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "neighbors":
        result = action_neighbors(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "path":
        if not args.source or not args.target:
            print("Error: --source and --target required for path", file=sys.stderr)
            sys.exit(1)
        result = action_path(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "pattern":
        if not args.pattern:
            print("Error: --pattern required", file=sys.stderr)
            sys.exit(1)
        result = action_pattern(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "subgraph":
        if not args.seeds:
            print("Error: --seeds required", file=sys.stderr)
            sys.exit(1)
        result = action_subgraph(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "stats":
        graph = load_json(args.input)
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        print(f"Nodes: {len(nodes)}, Edges: {len(edges)}")
        type_counts = set(n.get("type", "") for n in nodes)
        rel_counts = set(e.get("relation", "") for e in edges)
        print(f"Types: {', '.join(sorted(type_counts))}")
        print(f"Relations: {', '.join(sorted(rel_counts))}")
    elif args.action == "export":
        result = action_export(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
