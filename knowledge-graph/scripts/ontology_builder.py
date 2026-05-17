#!/usr/bin/env python3
"""Ontology Builder - Construct schema/ontology for a knowledge graph domain.

This script defines the concept types and relation types that form the backbone
of a knowledge graph. It supports JSON/YAML export and can suggest ontology
extensions based on domain description.

Usage:
    python ontology_builder.py --action list
    python ontology_builder.py --action suggest --domain "computer science"
    python ontology_builder.py --action export --format json --output schema.json
    python ontology_builder.py --action build --domain "biology" --concepts Person,Organization,Concept --relations WORKS_AT,DISCOVERED
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ============================================================================
# Built-in ontology definitions
# ============================================================================

DEFAULT_CONCEPTS: list[dict[str, Any]] = [
    {"type": "Person", "description": "A human being, named individual", "attributes": ["name", "birth_date", "nationality", "occupation"]},
    {"type": "Organization", "description": "A group of people constituted as a body", "attributes": ["name", "founded", "location", "type"]},
    {"type": "Concept", "description": "An abstract idea, theory, or notion", "attributes": ["name", "domain", "definition"]},
    {"type": "Location", "description": "A geographical place or region", "attributes": ["name", "country", "coordinates"]},
    {"type": "Event", "description": "A happening or occurrence at a point in time", "attributes": ["name", "date", "location", "description"]},
    {"type": "Artifact", "description": "A physical or digital object of interest", "attributes": ["name", "type", "created_date", "creator"]},
    {"type": "Process", "description": "A series of actions or steps", "attributes": ["name", "description", "inputs", "outputs"]},
    {"type": "Knowledge", "description": "Facts, information, skills acquired through experience or education", "attributes": ["name", "type", "source", "confidence"]},
]

DEFAULT_RELATIONS: list[dict[str, Any]] = [
    {"relation": "WORKS_AT", "source": "Person", "target": "Organization", "description": "Employment or affiliation relationship"},
    {"relation": "LOCATED_IN", "source": "Location", "target": "Location", "description": "Geographic containment"},
    {"relation": "PART_OF", "source": "Entity", "target": "Entity", "description": "Meronymic/part-whole relationship"},
    {"relation": "RELATED_TO", "source": "Entity", "target": "Entity", "description": "Generic associative relationship"},
    {"relation": "DISCOVERED", "source": "Person", "target": "Concept", "description": "Discovery or invention"},
    {"relation": "CREATED", "source": "Person", "target": "Artifact", "description": "Creation or authorship"},
    {"relation": "OCCURRED_AT", "source": "Event", "target": "Location", "description": "Event location"},
    {"relation": "OCCURRED_AT_TIME", "source": "Event", "target": "Concept", "description": "Temporal anchor"},
    {"relation": "INSTANCE_OF", "source": "Entity", "target": "Entity", "description": "Individual-to-class relationship"},
    {"relation": "DEPENDS_ON", "source": "Entity", "target": "Entity", "description": "Dependency relationship"},
    {"relation": "CAUSES", "source": "Entity", "target": "Entity", "description": "Causal relationship"},
    {"relation": "REFINES", "source": "Entity", "target": "Entity", "description": "Refinement or improvement"},
]


def load_custom_types(args: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    """Load user-provided concept and relation types from CLI or defaults."""
    concepts = DEFAULT_CONCEPTS[:]
    if args.concepts:
        for name in args.concepts.split(","):
            concepts.append({"type": name.strip(), "description": f"User-defined: {name.strip()}", "attributes": ["name", "description"]})

    relations = DEFAULT_RELATIONS[:]
    if args.relations:
        for entry in args.relations.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                relations.append({"relation": parts[0], "source": parts[1], "target": parts[2], "description": "User-defined relation"})
            elif len(parts) == 1:
                relations.append({"relation": parts[0], "source": "Entity", "target": "Entity", "description": "User-defined relation"})

    return concepts, relations


def action_list() -> dict:
    """Return the full default ontology."""
    return {"concepts": DEFAULT_CONCEPTS, "relations": DEFAULT_RELATIONS}


def action_suggest(domain: str) -> dict:
    """Suggest ontology extensions based on a domain description.

    In a production system this would call an LLM. For the skill, we return
    the base ontology and instruct the model to extend it based on the domain.
    """
    domain_domain_map: dict[str, list[dict]] = {
        "computer": [
            {"type": "Algorithm", "description": "A step-by-step procedure for computation", "attributes": ["name", "complexity", "inputs", "outputs"]},
            {"type": "Software", "description": "A program or collection of programs", "attributes": ["name", "language", "version", "license"]},
            {"type": "Hardware", "description": "Physical components of a computer system", "attributes": ["name", "specs", "manufacturer"]},
            {"type": "Dataset", "description": "A collection of data for analysis or training", "attributes": ["name", "size", "format", "domain"]},
            {"type": "Metric", "description": "A quantitative measure", "attributes": ["name", "unit", "range", "description"]},
        ],
        "biology": [
            {"type": "Species", "description": "A biological species", "attributes": ["name", "classification", "habitat", "status"]},
            {"type": "Gene", "description": "A unit of heredity", "attributes": ["name", "chromosome", "function", "organism"]},
            {"type": "Protein", "description": "A macromolecule", "attributes": ["name", "function", "structure", "organism"]},
            {"type": "Disease", "description": "A medical condition", "attributes": ["name", "causes", "symptoms", "treatments"]},
            {"type": "Drug", "description": "A medicinal substance", "attributes": ["name", "type", "target", "side_effects"]},
        ],
        "history": [
            {"type": "Era", "description": "A period of history", "attributes": ["name", "start", "end", "description"]},
            {"type": "Culture", "description": "A civilization or cultural group", "attributes": ["name", "region", "period", "language"]},
            {"type": "Religion", "description": "A system of faith and worship", "attributes": ["name", "origin", "followers", "texts"]},
            {"type": "Invention", "description": "A novel creation or device", "attributes": ["name", "inventor", "date", "impact"]},
        ],
    }

    domain_lower = domain.lower()
    suggestions = []
    for keyword, items in domain_domain_map.items():
        if keyword in domain_lower:
            suggestions.extend(items)

    if not suggestions:
        suggestions = [
            {"type": f"CustomDomainEntity", "description": f"Entity type relevant to {domain}", "attributes": ["name", "description", "properties"]},
        ]

    return {
        "domain": domain,
        "suggested_concepts": suggestions,
        "base_concepts": DEFAULT_CONCEPTS,
        "base_relations": DEFAULT_RELATIONS,
    }


def action_export(concepts: list[dict], relations: list[dict], fmt: str, output: str | None) -> str:
    """Export the ontology in the requested format."""
    data = {"concepts": concepts, "relations": relations}

    if fmt == "json":
        content = json.dumps(data, indent=2, ensure_ascii=False)
    elif fmt == "yaml":
        # Simple YAML-ish format (no PyYAML dependency)
        lines = ["concepts:", ""]
        for c in concepts:
            lines.append(f"  - type: {c['type']}")
            lines.append(f"    description: {c['description']}")
            lines.append(f"    attributes:")
            for attr in c.get("attributes", []):
                lines.append(f"      - {attr}")
            lines.append("")
        lines.append("relations:")
        for r in relations:
            lines.append(f"  - relation: {r['relation']}")
            lines.append(f"    source: {r['source']}")
            lines.append(f"    target: {r['target']}")
            lines.append(f"    description: {r['description']}")
            lines.append("")
        content = "\n".join(lines)
    else:
        return json.dumps(data, indent=2, ensure_ascii=False)

    if output:
        Path(output).write_text(content, encoding="utf-8")
        return f"Ontology exported to {output}"

    return content


def main() -> None:
    parser = argparse.ArgumentParser(description="Ontology Builder for Knowledge Graphs")
    parser.add_argument("--action", required=True, choices=["list", "suggest", "export", "build"],
                        help="Action to perform")
    parser.add_argument("--domain", type=str, help="Domain description for suggestion/build")
    parser.add_argument("--concepts", type=str, help="Comma-separated custom concept types")
    parser.add_argument("--relations", type=str, help="Comma-separated custom relations (NAME:SRC:TGT)")
    parser.add_argument("--format", choices=["json", "yaml"], default="json", help="Export format")
    parser.add_argument("--output", type=str, help="Output file path")
    args = parser.parse_args()

    if args.action == "list":
        result = action_list()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "suggest":
        if not args.domain:
            print("Error: --domain is required for suggest action", file=sys.stderr)
            sys.exit(1)
        result = action_suggest(args.domain)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "export":
        concepts, relations = load_custom_types(args)
        result = action_export(concepts, relations, args.format, args.output)
        print(result)

    elif args.action == "build":
        if not args.domain:
            print("Error: --domain is required for build action", file=sys.stderr)
            sys.exit(1)
        concepts, relations = load_custom_types(args)
        suggestion = action_suggest(args.domain)
        combined_concepts = suggestion.get("suggested_concepts", []) + concepts
        # Deduplicate by type name
        seen = set()
        unique_concepts = []
        for c in combined_concepts:
            if c["type"] not in seen:
                seen.add(c["type"])
                unique_concepts.append(c)
        result = {"domain": args.domain, "concepts": unique_concepts, "relations": relations}
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Ontology built for '{args.domain}' and saved to {args.output}")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
