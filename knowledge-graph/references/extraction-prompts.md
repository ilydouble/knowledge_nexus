# Knowledge Graph Extraction Prompts

Templates for LLM-powered entity and relation extraction.

## Template 1: Full Extraction (All Entities & Relations)

```
You are a knowledge graph extraction assistant.

## Ontology
{include ontology from ontology_builder.py output}

## Task
Extract all entities and relations from the following text.

## Output Format
Return a JSON object with this exact structure:

{
  "nodes": [
    {
      "id": "<hash_of_type_label>",
      "label": "<display name>",
      "type": "<one of the concept types>",
      "description": "<brief description>",
      "attributes": { "<key>": "<value>" }
    }
  ],
  "edges": [
    {
      "source": "<node_id>",
      "target": "<node_id>",
      "relation": "<one of the relation types>",
      "attributes": { "<key>": "<value>" }
    }
  ]
}

## Rules
1. Use the concept types and relation types from the ontology
2. Generate stable IDs: use lowercase(type) + "_" + lowercase(label.replace(" ", "_"))
3. Include ALL entities you can find — do not limit the number
4. Only create edges where the relation is clearly stated or strongly implied
5. Set confidence to 0.8+ only when you are fairly sure
6. If an entity doesn't fit any concept type, use "Knowledge" as default type
7. For relations not in the ontology, use "RELATED_TO" as fallback

## Text
"""
{insert text here}
"""
```

## Template 2: Entity-Only Extraction

```
Extract all entity mentions from the text.

Output JSON:
{
  "nodes": [
    {
      "id": "<unique_id>",
      "label": "<name>",
      "type": "<type>",
      "attributes": {}
    }
  ]
}

Rules:
- One node per unique entity (deduplicate by label)
- Assign types from: Person, Organization, Concept, Location, Event, Artifact, Process, Knowledge
- Do NOT create any edges
```

## Template 3: Relation-Only Extraction (Given Entities)

```
Given these entities:
{list of entity IDs and labels}

Find all relations between them in the text below.

Output JSON:
{
  "edges": [
    {
      "source": "<entity_id>",
      "target": "<entity_id>",
      "relation": "<relation_type>",
      "attributes": { "evidence": "<quoted text snippet>" }
    }
  ]
}

Available relations: {list from ontology}
```

## Template 4: Attribute Extraction

```
For each entity in the graph, extract additional attributes from the text.

Entities:
{list of entity IDs}

Text:
"""
{text}
"""

Output JSON:
{
  "updates": [
    {
      "id": "<entity_id>",
      "attributes": { "<key>": "<value>" }
    }
  ]
}
```

## Template 5: Domain-Specific Extraction

```
You are extracting knowledge for the {domain} domain.

## Domain-Specific Concept Types
{domain-suggested concepts from ontology_builder suggest action}

## Domain-Specific Relation Types
{domain-suggested relations from ontology_builder suggest action}

Extract entities and relations specific to this domain from:
"""
{text}
"""

Use the domain-specific types above. For anything not covered, fall back to the base ontology.
```

## Entity ID Generation Strategy

For stable entity IDs, use:
```
id = f"{type.lower()}_{label.lower().replace(' ', '_')}"
```

Example:
- "OpenAI" → type="Organization" → id: "organization_openai"
- "GPT-4" → type="Concept" → id: "concept_gpt-4"
- "Andrew Ng" → type="Person" → id: "person_andrew_ng"

For ambiguous entities, append a short index:
- "OpenAI" (first) → "organization_openai"
- "OpenAI" (second occurrence, already exists) → skip, reuse existing ID
