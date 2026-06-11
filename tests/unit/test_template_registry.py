from core.services.template_adapter import (
    HyperExtractTemplateAdapter,
    TemplateRegistry,
    TemplateSelector,
)


def test_registry_discovers_full_bundled_template_library():
    registry = TemplateRegistry()

    records = registry.list()
    template_ids = {record.template_id for record in records}

    assert len(records) >= 30
    assert "finance/earnings_summary" in template_ids
    assert "medicine/drug_interaction" in template_ids
    assert "industry/equipment_topology" in template_ids
    assert "legal/case_citation" in template_ids


def test_registry_filters_templates_by_type_tag_and_language():
    registry = TemplateRegistry()

    graph_templates = registry.list(filter_by_type="graph")
    finance_templates = registry.list(filter_by_tag="finance")
    zh_templates = registry.list(filter_by_language="zh")

    assert graph_templates
    assert all(record.template_type == "graph" for record in graph_templates)
    assert finance_templates
    assert all("finance" in record.tags for record in finance_templates)
    assert zh_templates
    assert len(zh_templates) == len(registry.list())


def test_registry_records_template_hash_for_replay():
    registry = TemplateRegistry()

    record = registry.get("general/base_graph")

    assert record is not None
    assert record.template_hash
    assert len(record.template_hash) == 64
    assert record.relative_path == "general/base_graph.yaml"


def test_adapter_template_meta_includes_registry_tracking_fields():
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt("general")

    assert result is not None
    assert result.template_meta["template_id"] == "nexus/general"
    assert result.template_meta["relative_path"] == "nexus/general.yaml"
    assert len(result.template_meta["template_hash"]) == 64


def test_selector_returns_ranked_doc_type_candidates():
    selector = TemplateSelector()

    selections = selector.select("contract", max_candidates=5)

    assert selections
    # nexus/contract is the primary candidate (first in DOC_TYPE_TEMPLATE_HINTS)
    assert selections[0].template_id == "nexus/contract"
    assert selections[0].template_type == "graph"
    assert selections[0].is_primary is True
    # HE legal templates follow as secondary hints
    assert any(selection.template_id == "legal/contract_obligation" for selection in selections)
    assert all(selection.template_hash for selection in selections)


def test_selector_falls_back_to_general_template_for_unknown_doc_type():
    selector = TemplateSelector()

    selections = selector.select("unknown_doc_type", max_candidates=2)

    assert selections
    assert selections[0].template_id == "nexus/general"
    assert selections[0].reason == "fallback"


def test_selector_prefers_smart_campus_template_for_campus_documents():
    selector = TemplateSelector()

    selections = selector.select("smart_campus", max_candidates=3)

    assert selections
    assert selections[0].template_id == "nexus/smart_campus"
    assert selections[0].is_primary is True
    assert any(selection.template_id == "industry/equipment_topology" for selection in selections)


def test_adapter_loads_smart_campus_ontology():
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt("smart_campus")

    assert result is not None
    assert not result.is_native_fallback
    types = {concept["type"] for concept in result.ontology["concepts"]}
    relations = {relation["relation"] for relation in result.ontology["relations"]}
    assert {"Building", "Space", "Equipment", "Point", "FaultEvent"}.issubset(types)
    assert {"LOCATED_IN", "FEEDS", "HAS_POINT", "TRIGGERS"}.issubset(relations)


def test_smart_campus_ontology_supports_pi_agent_native_graph_building():
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt("smart_campus")

    assert result is not None
    types = {concept["type"] for concept in result.ontology["concepts"]}
    relations = {relation["relation"] for relation in result.ontology["relations"]}
    assert {"GraphWorkspace", "CandidateBatch"}.issubset(types)
    assert {"PRODUCES_CANDIDATE", "REVIEWS_CANDIDATE", "COMMITS_TO_GRAPH", "QUERIES_GRAPH"}.issubset(relations)
    assert "EXPORTS_TO" not in relations
