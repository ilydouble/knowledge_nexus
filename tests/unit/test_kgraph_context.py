from nexus.services.content_parser import ParsedContent
from nexus.services.document_classifier import DocumentClassifier
from nexus.services.kgraph_context import KGraphContextBuilder


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
    assert "Component" in section["entity_hints"]
    assert "DEPENDS_ON" in section["relation_hints"]
    assert context["metadata"]["published_at"] == "2026-06-01"
    assert context["metadata"]["version"] == "v2"


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
