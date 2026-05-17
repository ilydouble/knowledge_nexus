from __future__ import annotations

from nexus.models import GraphEdge, GraphNode, GraphResult


class PermissionFilter:
    def filter_graph(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> GraphResult:
        filtered: list[GraphNode] = []
        hidden_count = 0
        for node in nodes:
            if node.accessible:
                filtered.append(node)
                continue
            hidden_count += 1
            filtered.append(
                GraphNode(
                    id=node.id,
                    uri=None,
                    label="Encrypted Node",
                    summary=None,
                    layer=node.layer,
                    accessible=False,
                    properties={},
                )
            )
        return GraphResult(nodes=filtered, edges=edges, hidden_node_count=hidden_count)

