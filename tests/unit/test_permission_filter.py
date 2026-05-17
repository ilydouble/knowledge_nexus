from nexus.models import GraphEdge, GraphNode, KnowledgeLayer
from nexus.services.permissions import PermissionFilter


def test_permission_filter_redacts_inaccessible_nodes_without_content_leakage():
    nodes = [
        GraphNode(id="a", uri="cloudreve://my/a.md", label="Allowed Plan", summary="safe", accessible=True),
        GraphNode(id="b", uri="cloudreve://other/secret.md", label="Secret Payroll", summary="salary", accessible=False),
    ]
    edges = [
        GraphEdge(
            id="e1",
            source="a",
            target="b",
            relation="RELATED_TO",
            layer=KnowledgeLayer.L2,
            owner_scope="team:rnd",
            source_file_uri="cloudreve://my/a.md",
            visibility="team",
        )
    ]

    result = PermissionFilter().filter_graph(nodes, edges)

    hidden = next(node for node in result.nodes if node.id == "b")
    assert hidden.label == "Encrypted Node"
    assert hidden.summary is None
    assert hidden.uri is None
    assert result.hidden_node_count == 1
    assert result.edges == edges

