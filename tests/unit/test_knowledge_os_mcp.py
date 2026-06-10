import json

import nexus.mcp_server as mcp_server
from nexus.knowledge_os.store import InMemoryKnowledgeOSStore
from nexus.repositories.memory import InMemoryRepository


def test_mcp_candidate_tools_return_stable_json(monkeypatch):
    monkeypatch.setattr(mcp_server, "_knowledge_os_store", InMemoryKnowledgeOSStore())
    monkeypatch.setattr(mcp_server, "_repo", InMemoryRepository())

    created = json.loads(
        mcp_server.run_candidate_extraction(
            uri="cloudreve://my/design.md",
            candidate_entities_json='[{"id":"api","label":"API"}]',
            candidate_relations_json='[{"source":"api","target":"db","relation":"STORES_IN"}]',
            template_ids_json='["nexus/technical_doc"]',
        )
    )
    batch_id = created["batch"]["id"]
    edge_item = next(item for item in created["graph_items"] if item["kind"] == "edge")

    updated = json.loads(
        mcp_server.update_candidate_items(
            batch_id,
            json.dumps([{"item_id": edge_item["id"], "status": "accepted"}]),
        )
    )
    assert updated["updated"][0]["status"] == "accepted"

    preview = json.loads(mcp_server.preview_graph_changes(batch_id))
    assert preview["changes"][0]["action"] == "create_edge"

    committed = json.loads(mcp_server.commit_candidate_batch(batch_id))
    assert committed["status"] == "committed"
    assert committed["committed_items"] == 1

    evidence = json.loads(mcp_server.explain_graph_evidence("edge:api:STORES_IN:db"))
    assert evidence["evidence"][0]["source_uri"] == "cloudreve://my/design.md"
