from core.services.content_parser import ParsedContent
from core.services.document_classifier import DocumentClassifier
from core.services.kgraph_context import KGraphContextBuilder
from core.services.template_adapter import HyperExtractTemplateAdapter, TEMPLATE_MAP


def test_context_builder_exports_traceable_kgraph_json_contract():
    parsed = ParsedContent(
        text=(
            "--- Page 1 ---\n"
            "公司新闻。\n\n"
            "--- Page 3 ---\n"
            "数据平台依赖 PostgreSQL，搜索服务依赖 Milvus。负责人 Alice 负责上线。"
        ),
        metadata={"filename": "architecture.md", "version": "v2", "published_at": "2026-06-01"},
        chunks=[
            "公司新闻。",
            "数据平台依赖 PostgreSQL，搜索服务依赖 Milvus。负责人 Alice 负责上线。",
        ],
        file_type="text",
    )
    classification = DocumentClassifier().classify(
        "architecture.md",
        content_preview=parsed.text[:600],
        file_type=parsed.file_type,
    )

    context = KGraphContextBuilder().build(
        uri="cloudreve://team/architecture.md",
        parsed=parsed,
        classification=classification,
        extraction_batch_id="batch-1",
    )

    assert context["document_id"].startswith("doc_")
    assert context["source_id"] == "cloudreve://team/architecture.md"
    assert context["extraction_batch_id"] == "batch-1"
    assert context["classification"]["doc_type"] == "technical_doc"
    assert context["classification"]["ontology_id"] == "technical_doc"
    assert context["classification"]["should_extract"] is True
    assert len(context["sections"]) == 1
    section = context["sections"][0]
    assert section["section_id"] == f"{context['document_id']}_section_1"
    assert section["title"] == "Page 3"
    assert section["relevance_score"] > 0
    assert "PostgreSQL" in section["text"]
    assert section["source_span"]["page"] == 3
    assert section["source_span"]["start_char"] >= 0
    assert section["source_span"]["end_char"] > section["source_span"]["start_char"]
    # technical_doc uses nexus/technical_doc.yaml ontology hints.
    assert len(section["entity_hints"]) > 0
    assert len(section["relation_hints"]) > 0
    assert "Component" in section["entity_hints"]
    assert "DEPENDS_ON" in section["relation_hints"]
    # template_meta must be present and correctly identify the adapted template
    assert "template_meta" in context["classification"]
    meta = context["classification"]["template_meta"]
    assert meta["name"] == "technical_doc"   # nexus/technical_doc.yaml
    assert meta["type"] == "graph"
    assert context["classification"]["primary_template_id"] == "nexus/technical_doc"
    assert context["classification"]["primary_template_type"] == "graph"
    assert context["classification"]["selected_templates"]
    assert context["classification"]["selected_templates"][0]["template_id"] == "nexus/technical_doc"
    assert len(context["classification"]["selected_templates"][0]["template_hash"]) == 64
    assert context["metadata"]["published_at"] == "2026-06-01"
    assert context["metadata"]["version"] == "v2"


def test_context_builder_keeps_native_technical_doc_hints_with_template_candidates():
    parsed = ParsedContent(
        text="AuthService 调用 POST /api/users，并将数据存储在 PostgreSQL。",
        metadata={"filename": "api_design.md"},
        chunks=["AuthService 调用 POST /api/users，并将数据存储在 PostgreSQL。"],
        file_type="text",
    )
    classification = DocumentClassifier().classify(
        "api_design.md",
        content_preview=parsed.text,
        file_type=parsed.file_type,
    )

    context = KGraphContextBuilder().build(
        uri="cloudreve://team/api_design.md",
        parsed=parsed,
        classification=classification,
        extraction_batch_id="batch-technical",
    )

    section = context["sections"][0]
    template_ids = [
        template["template_id"]
        for template in context["classification"]["selected_templates"]
    ]
    assert "Component" in section["entity_hints"]
    assert "DEPENDS_ON" in section["relation_hints"]
    assert "general/base_graph" in template_ids


def test_context_builder_keeps_top_windows_and_drops_low_signal_chunks():
    parsed = ParsedContent(
        text="\n\n".join(
            [
                "午餐安排和停车说明。",
                "AuthService 调用 POST /api/users，并将数据存储在 PostgreSQL。",
                "天气情况和办公区通知。",
                "DataPipeline 依赖 Redis，并返回 UserProfile。",
            ]
        ),
        metadata={"filename": "api_design.md"},
        chunks=[
            "午餐安排和停车说明。",
            "AuthService 调用 POST /api/users，并将数据存储在 PostgreSQL。",
            "天气情况和办公区通知。",
            "DataPipeline 依赖 Redis，并返回 UserProfile。",
        ],
        file_type="text",
    )
    classification = DocumentClassifier().classify(
        "api_design.md",
        content_preview=parsed.text[:600],
        file_type=parsed.file_type,
    )

    context = KGraphContextBuilder(max_sections=2).build(
        uri="cloudreve://team/api_design.md",
        parsed=parsed,
        classification=classification,
        extraction_batch_id="batch-2",
    )

    section_text = "\n".join(section["text"] for section in context["sections"])
    assert len(context["sections"]) == 2
    assert "AuthService" in section_text
    assert "DataPipeline" in section_text
    assert "午餐安排" not in section_text
    assert "天气情况" not in section_text


# ---------------------------------------------------------------------------
# HyperExtractTemplateAdapter unit tests
# ---------------------------------------------------------------------------

class TestHyperExtractTemplateAdapter:
    def setup_method(self):
        self.adapter = HyperExtractTemplateAdapter()

    def test_adapt_all_canonical_doc_types_return_full_ontology(self):
        """All TEMPLATE_MAP doc_types must return a full ontology (not fallback)."""
        for doc_type in ("general", "report", "email", "academic_paper", "technical_doc",
                         "meeting_minutes", "contract", "tabular_data"):
            result = self.adapter.adapt(doc_type)
            assert result is not None, f"{doc_type}: adapt() returned None"
            assert not result.is_native_fallback, f"{doc_type}: expected full adaptation"
            assert result.ontology.get("concepts"), f"{doc_type}: no concepts"
            assert result.ontology.get("relations"), f"{doc_type}: no relations"
            assert result.ontology.get("instructions"), f"{doc_type}: no instructions"

    def test_adapt_contract_uses_nexus_yaml(self):
        """contract → nexus/contract.yaml (type:graph) → Party/Obligation concepts."""
        result = self.adapter.adapt("contract")
        assert result is not None and not result.is_native_fallback
        types = {c["type"] for c in result.ontology["concepts"]}
        assert "Party" in types
        assert "Obligation" in types

    def test_adapt_meeting_minutes_uses_nexus_yaml(self):
        """meeting_minutes → nexus/meeting_minutes.yaml (type:graph) → Task/Decision."""
        result = self.adapter.adapt("meeting_minutes")
        assert result is not None and not result.is_native_fallback
        types = {c["type"] for c in result.ontology["concepts"]}
        assert "Task" in types
        assert "Decision" in types

    def test_adapt_general_concepts_and_relations(self):
        """general → nexus/general.yaml: broad entity types, graph relations."""
        result = self.adapter.adapt("general")
        assert result is not None and not result.is_native_fallback
        types = [c["type"] for c in result.ontology["concepts"]]
        assert len(types) > 0
        rel_names = [r["relation"] for r in result.ontology["relations"]]
        assert len(rel_names) > 0

    def test_adapt_academic_paper_concepts(self):
        """academic_paper → nexus/academic_paper.yaml: Researcher/Method/Dataset vocabulary."""
        result = self.adapter.adapt("academic_paper")
        assert result is not None and not result.is_native_fallback
        types = {c["type"] for c in result.ontology["concepts"]}
        assert any(t in types for t in ("Researcher", "Method", "Dataset"))

    def test_adapt_technical_doc_uses_nexus_yaml(self):
        """technical_doc → nexus/technical_doc.yaml: Component/API/Database vocabulary."""
        result = self.adapter.adapt("technical_doc")
        assert result is not None and not result.is_native_fallback
        types = {c["type"] for c in result.ontology["concepts"]}
        assert "Component" in types
        assert "API" in types

    def test_template_meta_contains_tracking_fields(self):
        """template_meta must always expose name, type, tags, identifiers."""
        result = self.adapter.adapt("general")
        assert result is not None
        meta = result.template_meta
        assert "name" in meta and meta["name"] == "general"
        assert "type" in meta and meta["type"] == "graph"
        assert "tags" in meta
        assert "identifiers" in meta

    def test_all_mapped_doc_types_resolve_a_template(self):
        """Every entry in TEMPLATE_MAP must load successfully (templates on disk)."""
        for doc_type in TEMPLATE_MAP:
            result = self.adapter.adapt(doc_type)
            assert result is not None, f"{doc_type}: adapt() returned None — template missing?"
