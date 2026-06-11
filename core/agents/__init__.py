"""Strands-based agents for knowledge_nexus.

Agents
------
classifier_agent   — Template selection fallback when keyword confidence < 0.4
schema_agent       — Propose a new nexus-v1 schema for unknown document types
graph_qa_agent     — Answer natural-language questions from the knowledge graph
graph_completion_agent — Find graph gaps and suggest missing links
"""

from core.agents.classifier_agent import create_classifier_agent
from core.agents.graph_completion_agent import create_graph_completion_agent
from core.agents.graph_qa_agent import create_graph_qa_agent
from core.agents.schema_agent import create_schema_agent

__all__ = [
    "create_classifier_agent",
    "create_schema_agent",
    "create_graph_qa_agent",
    "create_graph_completion_agent",
]
