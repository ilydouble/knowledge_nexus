from nexus.services.template_adapter import HyperExtractTemplateAdapter, TemplateRegistry


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
    assert result.template_meta["template_id"] == "general/base_graph"
    assert result.template_meta["relative_path"] == "general/base_graph.yaml"
    assert len(result.template_meta["template_hash"]) == 64
