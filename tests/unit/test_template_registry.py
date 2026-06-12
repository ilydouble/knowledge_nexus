from core.services.template_adapter import (
    HyperExtractTemplateAdapter,
    TemplateRegistry,
)


def test_registry_discovers_full_bundled_template_library():
    registry = TemplateRegistry()

    records = registry.list()
    template_ids = {record.template_id for record in records}

    # Exactly 37 Hyper-Extract templates; no nexus/ templates
    assert len(records) == 37
    assert not any(tid.startswith("nexus/") for tid in template_ids)
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


def test_adapter_adapt_by_id_graph_template():
    """adapt_by_id works for a standard graph template."""
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt_by_id("general/base_graph")

    assert result is not None
    assert not result.is_native_fallback
    assert len(result.ontology["concepts"]) > 0
    assert len(result.ontology["relations"]) > 0
    assert result.template_meta["template_id"] == "general/base_graph"
    assert len(result.template_meta["template_hash"]) == 64


def test_adapter_adapt_by_id_hypergraph_template():
    """adapt_by_id converts hypergraph templates (not native-fallback)."""
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt_by_id("legal/contract_obligation")

    assert result is not None
    assert not result.is_native_fallback
    types = {c["type"] for c in result.ontology["concepts"]}
    assert len(types) > 0


def test_adapter_adapt_by_id_flat_model_template():
    """adapt_by_id converts model/list/set templates to concepts-only ontology."""
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt_by_id("finance/earnings_summary")

    assert result is not None
    assert not result.is_native_fallback
    concepts = result.ontology["concepts"]
    assert len(concepts) > 0
    # Flat templates always get at least a RELATES_TO relation
    relations = result.ontology["relations"]
    assert any(r["relation"] == "RELATES_TO" for r in relations)


def test_adapter_adapt_falls_back_to_general_base_graph():
    """adapt(doc_type) always returns general/base_graph (no static mapping)."""
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt("any_doc_type")

    assert result is not None
    assert not result.is_native_fallback
    assert result.template_meta["template_id"] == "general/base_graph"


def test_adapter_adapt_by_id_returns_none_for_missing_template():
    """adapt_by_id returns None when the template_id is not in the registry."""
    adapter = HyperExtractTemplateAdapter()

    result = adapter.adapt_by_id("nexus/does_not_exist")

    assert result is None


def test_all_37_he_templates_produce_usable_ontology():
    """Every HE template returns a non-fallback OntologyResult with concepts."""
    registry = TemplateRegistry()
    adapter = HyperExtractTemplateAdapter(registry=registry)

    failures = []
    for record in registry.list():
        result = adapter.adapt_by_id(record.template_id)
        if result is None or result.is_native_fallback or not result.ontology.get("concepts"):
            failures.append(record.template_id)

    assert not failures, f"Templates with unusable ontology: {failures}"
