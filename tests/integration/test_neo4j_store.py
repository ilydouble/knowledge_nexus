import os

import pytest

from nexus.graph.neo4j_store import Neo4jGraphStore
from nexus.models import GraphEdge, GraphNode, KnowledgeLayer
from nexus.settings import Settings


pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run Neo4j integration tests")


def test_neo4j_store_writes_l3_link_and_reads_neighborhood():
    settings = Settings.from_env()
    store = Neo4jGraphStore(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    source_uri = "cloudreve://integration/neo4j-source.md"
    target_uri = "cloudreve://integration/neo4j-target.md"

    store.delete_by_uri_for_tests(source_uri)
    store.delete_by_uri_for_tests(target_uri)

    source = GraphNode(id="source", uri=source_uri, label="Neo4j Source", summary="source summary", layer=KnowledgeLayer.L3)
    target = GraphNode(id="target", uri=target_uri, label="Neo4j Target", summary="target summary", layer=KnowledgeLayer.L3)
    edge = GraphEdge(
        id="integration-edge",
        source=source.id,
        target=target.id,
        relation="RELATED_TO",
        layer=KnowledgeLayer.L3,
        owner_scope="user:integration-user",
        source_file_uri=source_uri,
        visibility="private",
    )

    store.upsert_file_node(source)
    store.upsert_file_node(target)
    store.upsert_edge(edge, source_uri=source_uri, target_uri=target_uri)

    result = store.neighborhood(source_uri, layers=[KnowledgeLayer.L3], depth=1)

    assert {node.uri for node in result.nodes} == {source_uri, target_uri}
    assert result.edges[0].relation == "RELATED_TO"
    assert result.edges[0].owner_scope == "user:integration-user"
    assert result.edges[0].visibility == "private"

    store.delete_by_uri_for_tests(source_uri)
    store.delete_by_uri_for_tests(target_uri)
    store.close()

