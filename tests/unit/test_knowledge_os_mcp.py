import json

from nexus.knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
from nexus.knowledge_os.interfaces.mcp import register_knowledge_os_tools
from nexus.repositories.memory import InMemoryRepository


class FakeMCP:
    def tool(self):
        def decorator(func):
            return func

        return decorator


def test_mcp_candidate_tools_return_stable_json():
    repository = InMemoryRepository()
    tools = register_knowledge_os_tools(
        FakeMCP(),
        store=InMemoryKnowledgeOSStore(),
        get_repository=lambda: repository,
    )
    created = json.loads(
        tools["run_candidate_extraction"](
            uri="cloudreve://my/design.md",
            candidate_entities_json='[{"id":"api","label":"API"}]',
            candidate_relations_json='[{"source":"api","target":"db","relation":"STORES_IN"}]',
            template_ids_json='["nexus/technical_doc"]',
        )
    )
    batch_id = created["batch"]["id"]
    edge_item = next(item for item in created["graph_items"] if item["kind"] == "edge")

    updated = json.loads(
        tools["update_candidate_items"](
            batch_id,
            json.dumps([{"item_id": edge_item["id"], "status": "accepted"}]),
        )
    )
    assert updated["updated"][0]["status"] == "accepted"

    preview = json.loads(tools["preview_graph_changes"](batch_id))
    assert preview["changes"][0]["action"] == "create_edge"

    committed = json.loads(tools["commit_candidate_batch"](batch_id))
    assert committed["status"] == "committed"
    assert committed["committed_items"] == 1

    evidence = json.loads(tools["explain_graph_evidence"]("edge:api:STORES_IN:db"))
    assert evidence["evidence"][0]["source_uri"] == "cloudreve://my/design.md"
