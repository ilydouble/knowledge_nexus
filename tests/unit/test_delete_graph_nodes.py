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


def _make_tools(neo4j=None):
    mcp = _FakeMCP()
    tools = register_knowledge_os_tools(
        mcp,
        store=MagicMock(),
        get_repository=lambda: MagicMock(),
        neo4j_store=neo4j,
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
