from __future__ import annotations

from nexus.models import GraphRagAnswer, GraphRagRequest
from nexus.repository import InMemoryRepository
from nexus.services.permissions import PermissionFilter


class GraphRagService:
    def __init__(self, repository: InMemoryRepository, permission_filter: PermissionFilter) -> None:
        self.repository = repository
        self.permission_filter = permission_filter

    def ask(self, request: GraphRagRequest) -> GraphRagAnswer:
        nodes, edges = self.repository.graph()
        scoped_nodes = [node for node in nodes if node.layer is None or node.layer in request.layers]
        scoped_edges = [edge for edge in edges if edge.layer in request.layers]
        result = self.permission_filter.filter_graph(scoped_nodes, scoped_edges)
        visible_labels = [node.label for node in result.nodes if node.accessible]
        if visible_labels:
            answer = "I found related accessible knowledge: " + ", ".join(visible_labels)
        else:
            answer = "I did not find accessible knowledge for this question yet."
        return GraphRagAnswer(answer=answer, citations=[node for node in result.nodes if node.accessible], hidden_node_count=result.hidden_node_count)

