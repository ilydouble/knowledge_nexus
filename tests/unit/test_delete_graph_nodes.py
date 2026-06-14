"""Smoke-test for the delete_graph_nodes MCP tool."""
import json
import sys
from unittest.mock import MagicMock

# Stub heavy optional deps that may not be installed in the test env
for _mod in ("mcp", "mcp.server", "mcp.server.fastmcp"):
    sys.modules.setdefault(_mod, MagicMock())

from knowledge_os.interfaces.mcp import register_knowledge_os_tools


class _FakeMCP:
    """Minimal MCP stub that records registered tool names."""

    def __init__(self):
        self.registered = []

    def tool(self):
        def deco(fn):
            self.registered.append(fn.__name__)
            return fn
        return deco


def _make_tools(neo4j=None, milvus=None, artifact=None, repo=None):
    mcp = _FakeMCP()
    if repo is None:
        repo = MagicMock()
        repo.get_document.return_value = None
    tools = register_knowledge_os_tools(
        mcp,
        store=MagicMock(),
        get_repository=lambda: repo,
        neo4j_store=neo4j,
        milvus_store=milvus,
        artifact_store=artifact,
    )
    return mcp, tools


def test_delete_graph_nodes_registered():
    mcp, tools = _make_tools(neo4j=MagicMock())
    assert "delete_graph_nodes" in tools, "not in return dict"
    assert "delete_graph_nodes" in mcp.registered, "decorator not invoked"


def test_delete_graph_nodes_happy_path():
    neo4j = MagicMock()
    neo4j.delete_file = MagicMock(return_value=None)
    _, tools = _make_tools(neo4j=neo4j)

    result = json.loads(tools["delete_graph_nodes"]("cloudreve://test/report.pdf"))

    assert result["deleted_uri"] == "cloudreve://test/report.pdf"
    assert result["neo4j"] == "nodes and edges removed"
    neo4j.delete_file.assert_called_once_with("cloudreve://test/report.pdf")


def test_delete_graph_nodes_no_neo4j():
    _, tools = _make_tools(neo4j=None)
    result = json.loads(tools["delete_graph_nodes"]("cloudreve://x"))
    assert "error" in result
    assert "Neo4j" in result["error"]


def test_delete_graph_nodes_neo4j_exception():
    neo4j = MagicMock()
    neo4j.delete_file = MagicMock(side_effect=RuntimeError("connection lost"))
    _, tools = _make_tools(neo4j=neo4j)

    result = json.loads(tools["delete_graph_nodes"]("cloudreve://x"))
    assert "error" in result
    assert "connection lost" in result["error"]


def test_delete_graph_nodes_cleans_milvus_when_configured():
    """Milvus chunks should be deleted when milvus_store is injected."""
    neo4j = MagicMock()
    milvus = MagicMock()

    _, tools = _make_tools(neo4j=neo4j, milvus=milvus)
    result = json.loads(tools["delete_graph_nodes"]("local:///docs/report.pdf"))

    milvus.delete_chunks_by_uri.assert_called_once_with("local:///docs/report.pdf")
    assert result["milvus"] == "chunks deleted"


def test_delete_graph_nodes_milvus_skipped_when_none():
    """When no milvus_store is configured, the field should indicate it was skipped."""
    neo4j = MagicMock()
    _, tools = _make_tools(neo4j=neo4j, milvus=None)
    result = json.loads(tools["delete_graph_nodes"]("local:///docs/report.pdf"))
    assert "skipped" in result["milvus"]


def test_delete_graph_nodes_cleans_minio_artifact():
    """MinIO artifact should be deleted when parsed_text_key is s3:// and artifact_store is set."""
    neo4j = MagicMock()
    milvus = MagicMock()
    artifact = MagicMock()

    repo = MagicMock()
    repo.get_document.return_value = {"parsed_text_key": "s3://knowledge-nexus/parsed-text/abcd/report.txt"}

    _, tools = _make_tools(neo4j=neo4j, milvus=milvus, artifact=artifact, repo=repo)
    result = json.loads(tools["delete_graph_nodes"]("local:///docs/report.pdf"))

    artifact.delete.assert_called_once_with("s3://knowledge-nexus/parsed-text/abcd/report.txt")
    assert result["artifact"] == "deleted"


def test_delete_graph_nodes_cleans_local_artifact():
    """local:// parsed_text_key should also be cleaned during hard delete."""
    neo4j = MagicMock()
    artifact = MagicMock()

    repo = MagicMock()
    local_key = "local:///app/data/artifacts/parsed-text/abcd1234/report.pdf.txt"
    repo.get_document.return_value = {"parsed_text_key": local_key}

    _, tools = _make_tools(neo4j=neo4j, artifact=artifact, repo=repo)
    result = json.loads(tools["delete_graph_nodes"]("local:///docs/report.pdf"))

    artifact.delete.assert_called_once_with(local_key)
    assert result["artifact"] == "deleted"


def test_delete_graph_nodes_artifact_skipped_when_no_key():
    """When parsed_text_key is absent, artifact cleanup should be skipped."""
    neo4j = MagicMock()
    artifact = MagicMock()

    repo = MagicMock()
    repo.get_document.return_value = {"parsed_text_key": None}

    _, tools = _make_tools(neo4j=neo4j, artifact=artifact, repo=repo)
    result = json.loads(tools["delete_graph_nodes"]("local:///docs/report.pdf"))

    artifact.delete.assert_not_called()
    assert "skipped" in result["artifact"]
