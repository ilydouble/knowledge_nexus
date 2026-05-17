from __future__ import annotations

from neo4j import GraphDatabase

from nexus.models import GraphEdge, GraphNode, GraphResult, KnowledgeLayer


class Neo4jGraphStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def upsert_file_node(self, node: GraphNode) -> None:
        if node.uri is None:
            raise ValueError("file graph nodes require a URI")
        with self.driver.session() as session:
            session.execute_write(self._upsert_file_node_tx, node)

    def upsert_edge(self, edge: GraphEdge, source_uri: str, target_uri: str) -> None:
        with self.driver.session() as session:
            session.execute_write(self._upsert_edge_tx, edge, source_uri, target_uri)

    def neighborhood(self, uri: str, layers: list[KnowledgeLayer], depth: int = 1) -> GraphResult:
        if depth != 1:
            raise ValueError("Neo4jGraphStore MVP supports depth=1")
        layer_values = [layer.value for layer in layers]
        with self.driver.session() as session:
            records = session.execute_read(self._neighborhood_tx, uri, layer_values)
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        for record in records:
            source = self._node_from_neo4j(record["source"])
            target = self._node_from_neo4j(record["target"])
            edge = self._edge_from_neo4j(record["edge"], source.id, target.id)
            nodes[source.id] = source
            nodes[target.id] = target
            edges[edge.id] = edge
        return GraphResult(nodes=list(nodes.values()), edges=list(edges.values()))

    def full_graph(self) -> GraphResult:
        """Return every node and every edge in the graph."""
        with self.driver.session() as session:
            node_records = session.execute_read(self._all_nodes_tx)
            edge_records = session.execute_read(self._all_edges_tx)
        nodes: dict[str, GraphNode] = {}
        for record in node_records:
            node = self._node_from_neo4j(record["n"])
            nodes[node.id] = node
        edges: dict[str, GraphEdge] = {}
        for record in edge_records:
            src = self._node_from_neo4j(record["source"])
            tgt = self._node_from_neo4j(record["target"])
            nodes.setdefault(src.id, src)
            nodes.setdefault(tgt.id, tgt)
            edge = self._edge_from_neo4j(record["edge"], src.id, tgt.id)
            edges[edge.id] = edge
        return GraphResult(nodes=list(nodes.values()), edges=list(edges.values()))

    def search_nodes(self, keyword: str, limit: int = 20) -> list[GraphNode]:
        """Full-graph label search — matches entities and file nodes alike."""
        with self.driver.session() as session:
            records = session.execute_read(self._search_nodes_tx, keyword, limit)
        return [self._node_from_neo4j(r["n"]) for r in records]

    def list_file_nodes(self, limit: int = 100) -> list[GraphNode]:
        """Return processed document nodes (exclude entity:// URI nodes)."""
        with self.driver.session() as session:
            records = session.execute_read(self._list_file_nodes_tx, limit)
        return [self._node_from_neo4j(r["n"]) for r in records]

    def list_entity_nodes(self, keyword: str = "", limit: int = 50) -> list[GraphNode]:
        """Return entity nodes, optionally filtered by label keyword."""
        with self.driver.session() as session:
            records = session.execute_read(self._list_entity_nodes_tx, keyword, limit)
        return [self._node_from_neo4j(r["n"]) for r in records]

    def get_document_subgraph(self, uri: str) -> GraphResult:
        """Return a document node + all entities it MENTIONS."""
        with self.driver.session() as session:
            records = session.execute_read(self._document_subgraph_tx, uri)
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        for record in records:
            src = self._node_from_neo4j(record["source"])
            tgt = self._node_from_neo4j(record["target"])
            edge = self._edge_from_neo4j(record["edge"], src.id, tgt.id)
            nodes[src.id] = src
            nodes[tgt.id] = tgt
            edges[edge.id] = edge
        return GraphResult(nodes=list(nodes.values()), edges=list(edges.values()))

    def delete_by_uri_for_tests(self, uri: str) -> None:
        with self.driver.session() as session:
            session.run("MATCH (n:NexusFile {uri: $uri}) DETACH DELETE n", uri=uri)

    @staticmethod
    def _upsert_file_node_tx(tx, node: GraphNode) -> None:
        tx.run(
            """
            MERGE (n:NexusFile {uri: $uri})
            SET n.id = $id,
                n.label = $label,
                n.summary = $summary,
                n.layer = $layer,
                n.accessible = $accessible
            """,
            uri=node.uri,
            id=node.id,
            label=node.label,
            summary=node.summary,
            layer=node.layer.value if node.layer else None,
            accessible=node.accessible,
        )

    @staticmethod
    def _upsert_edge_tx(tx, edge: GraphEdge, source_uri: str, target_uri: str) -> None:
        tx.run(
            """
            MERGE (source:NexusFile {uri: $source_uri})
            MERGE (target:NexusFile {uri: $target_uri})
            MERGE (source)-[edge:NEXUS_RELATION {id: $id}]->(target)
            SET edge.relation = $relation,
                edge.layer = $layer,
                edge.owner_scope = $owner_scope,
                edge.source_file_uri = $source_file_uri,
                edge.visibility = $visibility
            """,
            source_uri=source_uri,
            target_uri=target_uri,
            id=edge.id,
            relation=edge.relation,
            layer=edge.layer.value,
            owner_scope=edge.owner_scope,
            source_file_uri=edge.source_file_uri,
            visibility=edge.visibility,
        )

    @staticmethod
    def _neighborhood_tx(tx, uri: str, layers: list[str]):
        result = tx.run(
            """
            MATCH (source:NexusFile {uri: $uri})-[edge:NEXUS_RELATION]-(target:NexusFile)
            WHERE edge.layer IN $layers
            RETURN source, edge, target
            ORDER BY edge.id
            """,
            uri=uri,
            layers=layers,
        )
        return list(result)

    @staticmethod
    def _all_nodes_tx(tx):
        result = tx.run("MATCH (n:NexusFile) RETURN n")
        return list(result)

    @staticmethod
    def _all_edges_tx(tx):
        result = tx.run(
            """
            MATCH (source:NexusFile)-[edge:NEXUS_RELATION]->(target:NexusFile)
            RETURN source, edge, target
            ORDER BY edge.id
            """
        )
        return list(result)

    @staticmethod
    def _search_nodes_tx(tx, keyword: str, limit: int):
        result = tx.run(
            """
            MATCH (n:NexusFile)
            WHERE toLower(n.label) CONTAINS toLower($keyword)
            RETURN n
            ORDER BY n.label
            LIMIT $limit
            """,
            keyword=keyword, limit=limit,
        )
        return list(result)

    @staticmethod
    def _list_file_nodes_tx(tx, limit: int):
        result = tx.run(
            """
            MATCH (n:NexusFile)
            WHERE NOT n.uri STARTS WITH 'entity://'
            RETURN n
            ORDER BY n.label
            LIMIT $limit
            """,
            limit=limit,
        )
        return list(result)

    @staticmethod
    def _list_entity_nodes_tx(tx, keyword: str, limit: int):
        if keyword:
            result = tx.run(
                """
                MATCH (n:NexusFile)
                WHERE n.uri STARTS WITH 'entity://'
                  AND toLower(n.label) CONTAINS toLower($keyword)
                RETURN n ORDER BY n.label LIMIT $limit
                """,
                keyword=keyword, limit=limit,
            )
        else:
            result = tx.run(
                """
                MATCH (n:NexusFile)
                WHERE n.uri STARTS WITH 'entity://'
                RETURN n ORDER BY n.label LIMIT $limit
                """,
                limit=limit,
            )
        return list(result)

    @staticmethod
    def _document_subgraph_tx(tx, uri: str):
        result = tx.run(
            """
            MATCH (source:NexusFile)-[edge:NEXUS_RELATION]->(target:NexusFile)
            WHERE source.uri = $uri OR target.uri = $uri
            RETURN source, edge, target
            ORDER BY edge.relation
            """,
            uri=uri,
        )
        return list(result)

    @staticmethod
    def _node_from_neo4j(node) -> GraphNode:
        return GraphNode(
            id=node.get("id") or f"file:{node.get('uri')}",
            uri=node.get("uri"),
            label=node.get("label") or node.get("uri"),
            summary=node.get("summary"),
            layer=KnowledgeLayer(node["layer"]) if node.get("layer") else None,
            accessible=node.get("accessible", True),
        )

    @staticmethod
    def _edge_from_neo4j(edge, source_id: str, target_id: str) -> GraphEdge:
        return GraphEdge(
            id=edge["id"],
            source=source_id,
            target=target_id,
            relation=edge["relation"],
            layer=KnowledgeLayer(edge["layer"]),
            owner_scope=edge["owner_scope"],
            source_file_uri=edge["source_file_uri"],
            visibility=edge["visibility"],
        )

