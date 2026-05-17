#!/usr/bin/env python3
"""Knowledge Graph Extractor - Extract entities, relations and facts from text.

This script accepts a prompt describing what to extract and returns a structured
graph representation as JSON. The actual LLM extraction is orchestrated via
the deer-flow agent tools (code interpreter, LLM calls) — this script provides
the extraction template, validation, and post-processing.

Usage:
    python graph_extractor.py --action validate --input graph.json --schema ontology.json
    python graph_extractor.py --action dedup --input graph.json --strategy merge
    python graph_extractor.py --action stats --input graph.json
    python graph_extractor.py --action convert --input graph.json --format csv --output nodes.csv
    python graph_extractor.py --action merge --mode prompt --prompt "Extract all entities and relations about AI from this text"
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def load_json(path: str) -> dict:
    """Load a JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str, data: dict | list) -> None:
    """Save data as JSON."""
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def action_validate(args: argparse.Namespace) -> dict:
    """Validate a graph against an ontology schema."""
    graph = load_json(args.input)
    ontology = load_json(args.schema) if args.schema else {"concepts": [], "relations": []}

    concept_types = {c["type"] for c in ontology.get("concepts", [])}
    relation_types = {r["relation"] for r in ontology.get("relations", [])}

    errors: list[str] = []
    warnings: list[str] = []

    # Validate nodes
    nodes = graph.get("nodes", [])
    for node in nodes:
        ntype = node.get("type", "")
        if concept_types and ntype not in concept_types:
            warnings.append(f"Node type '{ntype}' not in ontology (allowed: {', '.join(sorted(concept_types))})")
        if "id" not in node:
            errors.append(f"Node missing 'id': {node}")
        if "label" not in node:
            warnings.append(f"Node missing 'label': {node.get('id', '?')}")

    # Validate edges
    edges = graph.get("edges", [])
    for edge in edges:
        rel = edge.get("relation", "")
        if relation_types and rel not in relation_types:
            warnings.append(f"Relation type '{rel}' not in ontology (allowed: {', '.join(sorted(relation_types))})")
        for field in ("source", "target"):
            if field not in edge:
                errors.append(f"Edge missing '{field}': {edge}")

    return {
        "valid": len(errors) == 0,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "errors": errors,
        "warnings": warnings,
    }


def action_dedup(args: argparse.Namespace) -> dict:
    """Deduplicate nodes in a graph."""
    graph = load_json(args.input)
    nodes = graph["nodes"]
    edges = graph["edges"]

    if args.strategy == "merge":
        # Merge nodes with same label (case-insensitive)
        seen: dict[str, dict] = {}
        for node in nodes:
            key = node.get("label", "").lower()
            if not key:
                key = node.get("id", "").lower()
            if key in seen:
                # Merge: keep both, mark one as duplicate
                seen[key].setdefault("aliases", []).append(node.get("id", ""))
                node["type"] = "Duplicate"
            else:
                seen[key] = node
        deduped = [n for n in nodes if n.get("type") != "Duplicate"]
        merged_count = len(nodes) - len(deduped)
    elif args.strategy == "remove_duplicates":
        # Remove exact duplicates based on (id, type, label)
        seen_keys: set[tuple] = set()
        deduped = []
        for node in nodes:
            key = (node.get("id"), node.get("type"), node.get("label"))
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(node)
        merged_count = 0
    else:
        deduped = nodes
        merged_count = 0

    output = {"nodes": deduped, "edges": edges}
    if args.output:
        save_json(args.output, output)
        print(f"Deduplicated graph saved to {args.output} ({merged_count} duplicates removed)")

    return {"original_nodes": len(nodes), "deduped_nodes": len(deduped), "merged": merged_count, "graph": output}


def action_stats(args: argparse.Namespace) -> str:
    """Return statistics about a graph."""
    graph = load_json(args.input)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    node_types: dict[str, int] = {}
    for n in nodes:
        t = n.get("type", "Unknown")
        node_types[t] = node_types.get(t, 0) + 1

    relation_types: dict[str, int] = {}
    for e in edges:
        r = e.get("relation", "Unknown")
        relation_types[r] = relation_types.get(r, 0) + 1

    # Degree distribution
    in_deg: dict[str, int] = {}
    out_deg: dict[str, int] = {}
    for e in edges:
        t = e.get("target", "")
        s = e.get("source", "")
        in_deg[t] = in_deg.get(t, 0) + 1
        out_deg[s] = out_deg.get(s, 0) + 1

    stats = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "density": f"{len(edges) / max(len(nodes) * (len(nodes) - 1), 1):.4f}" if len(nodes) > 1 else "N/A",
        "node_type_distribution": dict(sorted(node_types.items(), key=lambda x: -x[1])),
        "relation_type_distribution": dict(sorted(relation_types.items(), key=lambda x: -x[1])),
        "avg_in_degree": f"{sum(in_deg.values()) / max(len(in_deg), 1):.2f}",
        "avg_out_degree": f"{sum(out_deg.values()) / max(len(out_deg), 1):.2f}",
        "max_in_degree": max(in_deg.values()) if in_deg else 0,
        "max_out_degree": max(out_deg.values()) if out_deg else 0,
    }

    lines = [f"Nodes: {stats['node_count']}", f"Edges: {stats['edge_count']}", f"Density: {stats['density']}"]
    lines.append("\nNode type distribution:")
    for t, c in stats["node_type_distribution"].items():
        lines.append(f"  {t}: {c}")
    lines.append("\nRelation type distribution:")
    for r, c in stats["relation_type_distribution"].items():
        lines.append(f"  {r}: {c}")

    return "\n".join(lines)


def action_convert(args: argparse.Namespace) -> str:
    """Convert graph to CSV format."""
    graph = load_json(args.input)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    files_created = []
    if args.output:
        # Determine if nodes, edges, or both
        if nodes:
            node_path = args.output if not args.output.endswith(".csv") else args.output[:-4] + "_nodes.csv"
            with open(node_path, "w", newline="", encoding="utf-8") as f:
                if nodes:
                    writer = csv.DictWriter(f, fieldnames=nodes[0].keys())
                    writer.writeheader()
                    writer.writerows(nodes)
            files_created.append(node_path)

        if edges:
            edge_path = args.output if not args.output.endswith(".csv") else args.output[:-4] + "_edges.csv"
            with open(edge_path, "w", newline="", encoding="utf-8") as f:
                if edges:
                    writer = csv.DictWriter(f, fieldnames=edges[0].keys())
                    writer.writeheader()
                    writer.writerows(edges)
            files_created.append(edge_path)

        return f"Converted to CSV: {', '.join(files_created)}"

    return json.dumps({"nodes": nodes, "edges": edges}, indent=2, ensure_ascii=False)


def action_merge(args: argparse.Namespace) -> dict:
    """Merge two graph files or accept extraction prompt.

    --mode json: merge two graph JSON files
    --mode prompt: accept an extraction prompt (used for guidance, actual extraction via LLM in the skill flow)
    """
    if args.mode == "json":
        if not args.input2:
            print("Error: --input2 required for json merge mode", file=sys.stderr)
            sys.exit(1)
        g1 = load_json(args.input)
        g2 = load_json(args.input2)

        # Merge nodes by ID
        seen_ids: dict[str, dict] = {}
        for n in g1.get("nodes", []):
            seen_ids[n["id"]] = n
        for n in g2.get("nodes", []):
            if n["id"] not in seen_ids:
                seen_ids[n["id"]] = n

        # Merge edges
        edge_keys: set[tuple] = set()
        all_edges = []
        for e in g1.get("edges", []) + g2.get("edges", []):
            key = (e.get("source"), e.get("relation"), e.get("target"))
            if key not in edge_keys:
                edge_keys.add(key)
                all_edges.append(e)

        merged = {"nodes": list(seen_ids.values()), "edges": all_edges}

        if args.output:
            save_json(args.output, merged)
            print(f"Merged graph saved to {args.output}")

        return merged

    elif args.mode == "prompt":
        return {"mode": "prompt", "prompt": args.prompt, "status": "ready_for_extraction"}

    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge Graph Extractor")
    parser.add_argument("--action", required=True, choices=["validate", "dedup", "stats", "convert", "merge"],
                        help="Action to perform")
    parser.add_argument("--input", required=True, help="Input graph JSON file")
    parser.add_argument("--input2", help="Second input file (for merge)")
    parser.add_argument("--schema", help="Ontology schema JSON file (for validate)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--strategy", default="merge", choices=["merge", "remove_duplicates"], help="Dedup strategy")
    parser.add_argument("--format", default="csv", help="Output format")
    parser.add_argument("--mode", choices=["json", "prompt"], help="Merge mode")
    parser.add_argument("--prompt", type=str, help="Extraction prompt")
    args = parser.parse_args()

    if args.action == "validate":
        result = action_validate(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "dedup":
        result = action_dedup(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.action == "stats":
        print(action_stats(args))
    elif args.action == "convert":
        print(action_convert(args))
    elif args.action == "merge":
        result = action_merge(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
