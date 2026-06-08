import json

from nexus.services.document_classifier import CATEGORIES, DocumentClassifier
from nexus.services.knowledge_extractor import (
    DOCUMENT_TEMPLATES,
    ExtractedKnowledge,
    KnowledgeExtractor,
    MIN_ENTITY_CONFIDENCE,
    _MAP_REDUCE_THRESHOLD,
    _SEGMENT_SIZE,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def post(self, url, *, headers, json, timeout):
        self.requests.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(self.payload)


def test_knowledge_extractor_calls_glm47_chat_completion_and_normalizes_json():
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "summary": "这是一份架构说明。",
                            "tags": ["架构", "图谱"],
                            "entities": [{"label": "Knowledge Nexus", "type": "Project"}],
                            "relations": [],
                            "key_points": [{"content": "支持语义网盘", "type": "conclusion"}],
                        }
                    )
                }
            }
        ]
    }
    http_client = FakeHttpClient(payload)
    extractor = KnowledgeExtractor(api_key="test-key", model="glm-4.7", http_client=http_client)

    result = extractor.extract("Knowledge Nexus 是一个语义网盘。")

    assert result.summary == "这是一份架构说明。"
    assert result.tags == ["架构", "图谱"]
    assert result.entities[0]["id"] == "project_knowledge_nexus"
    request = http_client.requests[0]
    assert request["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["model"] == "glm-4.7"
    assert request["json"]["response_format"] == {"type": "json_object"}


def test_knowledge_extractor_uses_mock_result_without_api_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("BIGMODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    extractor = KnowledgeExtractor(api_key=None)

    result = extractor.extract("Infrared sensor thermal calibration.", doc_type="general")

    assert result.raw_response == {"mock": True}
    assert "Infrared" in result.summary


# ---------------------------------------------------------------------------
# Quality filtering (_normalize_result)
# ---------------------------------------------------------------------------

def _make_raw(entities, relations=None, summary="test"):
    return {
        "summary": summary,
        "tags": ["t"],
        "entities": entities,
        "relations": relations or [],
        "key_points": [],
        "confidence": 0.9,
    }


def test_normalize_drops_low_confidence_entities():
    extractor = KnowledgeExtractor(api_key="key", model="m", http_client=None)
    raw = _make_raw([
        {"id": "a", "label": "A", "type": "X", "confidence": 0.8},
        {"id": "b", "label": "B", "type": "X", "confidence": 0.3},  # should be dropped
    ])
    result = extractor._normalize_result(raw, "general")
    ids = {e["id"] for e in result.entities}
    assert "a" in ids
    assert "b" not in ids


def test_normalize_drops_relations_with_removed_endpoint():
    extractor = KnowledgeExtractor(api_key="key", model="m", http_client=None)
    raw = _make_raw(
        entities=[
            {"id": "a", "label": "A", "type": "X", "confidence": 0.9},
            {"id": "b", "label": "B", "type": "X", "confidence": 0.1},  # dropped
        ],
        relations=[
            {"source": "a", "target": "a", "relation": "SELF"},   # kept
            {"source": "a", "target": "b", "relation": "LINKS"},  # dropped (b removed)
        ],
    )
    result = extractor._normalize_result(raw, "general")
    assert len(result.entities) == 1
    assert len(result.relations) == 1
    assert result.relations[0]["relation"] == "SELF"


# ---------------------------------------------------------------------------
# Map-Reduce helpers
# ---------------------------------------------------------------------------

def test_split_text_produces_correct_segments():
    extractor = KnowledgeExtractor(api_key="key", model="m", http_client=None)
    text = "A" * (3 * _SEGMENT_SIZE)
    segments = extractor._split_text(text)
    assert len(segments) >= 3
    # All segments within budget
    for seg in segments:
        assert len(seg) <= _SEGMENT_SIZE


def test_merge_extractions_deduplicates_entities_and_relations():
    extractor = KnowledgeExtractor(api_key="key", model="m", http_client=None)
    e1 = ExtractedKnowledge(
        summary="S1", tags=["a", "b"],
        entities=[{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
        relations=[{"source": "x", "target": "y", "relation": "R"}],
        key_points=[], confidence=0.9,
    )
    e2 = ExtractedKnowledge(
        summary="S2", tags=["b", "c"],
        entities=[{"id": "y", "label": "Y"}, {"id": "z", "label": "Z"}],
        relations=[
            {"source": "x", "target": "y", "relation": "R"},  # duplicate
            {"source": "y", "target": "z", "relation": "Q"},  # new
        ],
        key_points=[], confidence=0.8,
    )
    merged = extractor._merge_extractions([e1, e2])
    entity_ids = {e["id"] for e in merged.entities}
    assert entity_ids == {"x", "y", "z"}
    assert len(merged.relations) == 2
    assert set(merged.tags) == {"a", "b", "c"}
    assert merged.confidence == 0.8  # min of 0.9 and 0.8


def test_extract_uses_single_pass_for_short_text():
    """Short texts must not trigger map-reduce (only 1 HTTP call)."""
    short_text = "Short text." * 10  # well below threshold
    payload = {
        "choices": [{"message": {"content": json.dumps(
            {"summary": "ok", "tags": [], "entities": [], "relations": [], "key_points": []}
        )}}]
    }
    http_client = FakeHttpClient(payload)
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
    extractor.extract(short_text)
    assert len(http_client.requests) == 1


def test_extract_uses_mapreduce_for_long_text():
    """Long texts must trigger multiple HTTP calls (one per segment + summary)."""
    long_text = "word " * (_MAP_REDUCE_THRESHOLD + 1000)  # above threshold
    payload = {
        "choices": [{"message": {"content": json.dumps(
            {"summary": "part", "tags": [], "entities": [], "relations": [], "key_points": []}
        )}}]
    }
    http_client = FakeHttpClient(payload)
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
    extractor.extract(long_text)
    # Must be more than 1 call (segments + synthesize_summary call)
    assert len(http_client.requests) > 1



# ---------------------------------------------------------------------------
# DocumentClassifier tests
# ---------------------------------------------------------------------------

class TestDocumentClassifier:
    def setup_method(self):
        self.clf = DocumentClassifier()

    def test_excel_extension_always_tabular(self):
        result = self.clf.classify("sales_2024.xlsx")
        assert result.doc_type == "tabular_data"
        assert result.strategy == "structural_summary"
        assert result.confidence == 1.0

    def test_parser_file_type_overrides_all(self):
        # Even a .txt file is tabular if parser says so
        result = self.clf.classify("data.txt", file_type="tabular_data")
        assert result.doc_type == "tabular_data"
        assert result.strategy == "structural_summary"

    def test_csv_small_row_count_not_tabular(self):
        result = self.clf.classify("data.csv", row_count=50)
        # Small CSV → not forced into tabular_data by row_count signal
        assert result.doc_type != "tabular_data" or result.confidence < 1.0

    def test_csv_large_row_count_is_tabular(self):
        result = self.clf.classify("data.csv", row_count=500)
        assert result.doc_type == "tabular_data"
        assert result.strategy == "structural_summary"

    def test_filename_keyword_academic_paper(self):
        result = self.clf.classify("research_paper_2024.pdf")
        assert result.doc_type == "academic_paper"

    def test_filename_keyword_meeting(self):
        result = self.clf.classify("2024_meeting_minutes.docx")
        assert result.doc_type == "meeting_minutes"

    def test_filename_keyword_report(self):
        result = self.clf.classify("monthly_report_may.pdf")
        assert result.doc_type == "report"

    def test_content_keyword_academic(self):
        preview = "Abstract: This paper proposes a new methodology for... doi:10.1234/xyz"
        result = self.clf.classify("unknown.pdf", content_preview=preview)
        assert result.doc_type == "academic_paper"

    def test_content_keyword_contract(self):
        preview = "AGREEMENT made between 甲方 and 乙方. The parties hereby agree..."
        result = self.clf.classify("doc.pdf", content_preview=preview)
        assert result.doc_type == "contract"

    def test_no_signal_falls_back_to_general(self):
        result = self.clf.classify("untitled.pdf")
        assert result.doc_type == "general"
        assert result.strategy == "llm_extract"

    def test_all_categories_have_strategy(self):
        """Every category must define a strategy."""
        for cat, meta in CATEGORIES.items():
            assert "strategy" in meta, f"{cat} is missing 'strategy'"
            assert meta["strategy"] in ("llm_extract", "structural_summary")

    def test_all_types_present_in_document_templates(self):
        for doc_type in ("tabular_data", "contract", "email", "academic_paper",
                         "technical_doc", "meeting_minutes", "report"):
            assert doc_type in DOCUMENT_TEMPLATES, f"{doc_type} missing from DOCUMENT_TEMPLATES"

    def test_each_template_has_rich_ontology_fields(self):
        """Every template must have concepts (with descriptions) and relations (with source/target)."""
        for doc_type, tmpl in DOCUMENT_TEMPLATES.items():
            assert "concepts" in tmpl, f"{doc_type}: missing 'concepts'"
            assert "relations" in tmpl, f"{doc_type}: missing 'relations'"
            assert "instructions" in tmpl, f"{doc_type}: missing 'instructions'"
            for concept in tmpl["concepts"]:
                assert "type" in concept and "description" in concept, \
                    f"{doc_type}: concept missing type or description: {concept}"
                assert concept["description"] != f"{concept['type']} entity", \
                    f"{doc_type}: concept '{concept['type']}' still has placeholder description"
            for rel in tmpl["relations"]:
                assert "relation" in rel and "source" in rel and "target" in rel, \
                    f"{doc_type}: relation missing relation/source/target: {rel}"
                # source/target must not be generic 'Entity' (except general fallback)
                assert rel["source"] != "Entity" or doc_type == "general", \
                    f"{doc_type}: relation '{rel['relation']}' has generic source 'Entity'"

    def test_prompt_contains_entity_descriptions(self):
        """_build_extraction_prompt should include entity descriptions from the resolved ontology.

        academic_paper → concept_graph template (type: graph), so the prompt will
        contain concept-graph entity types and relations, not the DOCUMENT_TEMPLATES
        Researcher / PROPOSES vocabulary.
        """
        http_client = FakeHttpClient({"choices": [{"message": {"content": "{}"}}]})
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
        ontology = extractor._get_ontology("academic_paper")
        prompt = extractor._build_extraction_prompt("sample text", ontology, "academic_paper")
        # The prompt always includes the structural sections
        assert "Extraction Instructions" in prompt
        # concept_graph template produces type-vocabulary concepts and relation hints
        assert len(ontology.get("concepts", [])) > 0
        assert len(ontology.get("relations", [])) > 0
        # The prompt must contain at least one concept type name and one relation name
        concept_types = [c["type"] for c in ontology["concepts"]]
        assert any(ct in prompt for ct in concept_types)
        rel_names = [r["relation"] for r in ontology["relations"]]
        assert any(rn in prompt for rn in rel_names)

    def test_get_ontology_falls_back_to_document_templates_for_hypergraph(self):
        """contract → hypergraph template → adapter returns is_native_fallback=True
        → _get_ontology must use DOCUMENT_TEMPLATES['contract'] instead."""
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None)
        ontology = extractor._get_ontology("contract")
        # DOCUMENT_TEMPLATES['contract'] has Party, Obligation, Right, Penalty, …
        types = {c["type"] for c in ontology.get("concepts", [])}
        assert "Party" in types, "Expected DOCUMENT_TEMPLATES fallback with 'Party' concept"

    def test_get_ontology_falls_back_to_document_templates_for_temporal_graph(self):
        """meeting_minutes → workflow_graph (temporal_graph) → native fallback."""
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None)
        ontology = extractor._get_ontology("meeting_minutes")
        types = {c["type"] for c in ontology.get("concepts", [])}
        assert "Task" in types, "Expected DOCUMENT_TEMPLATES fallback with 'Task' concept"

    def test_get_ontology_uses_template_adapter_for_graph_types(self):
        """general → base_graph (graph) → adapter is used, not DEFAULT_ONTOLOGY."""
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None)
        ontology = extractor._get_ontology("general")
        # base_graph entity examples include person, location, organization, …
        types = {c["type"].lower() for c in ontology.get("concepts", [])}
        assert len(types) > 0


# ---------------------------------------------------------------------------
# KnowledgeExtractor tabular path
# ---------------------------------------------------------------------------

def _make_tabular_payload():
    return {
        "choices": [{"message": {"content": json.dumps({
            "summary": "Sales dataset with 5000 rows.",
            "tags": ["sales", "tabular"],
            "entities": [
                {"id": "dataset_sales", "label": "Sales", "type": "Dataset",
                 "description": "Sales data", "confidence": 0.95},
            ],
            "relations": [],
            "key_points": [{"content": "5000 rows", "type": "fact"}],
        })}}]
    }


def test_extract_tabular_strategy_makes_single_llm_call():
    """structural_summary strategy → only ONE LLM call (no map-reduce)."""
    http_client = FakeHttpClient(_make_tabular_payload())
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
    structural_text = "Excel Workbook: sales.xlsx\nSheet 1: \"Data\" — 5000 rows × 3 columns\nColumns: Date, Product, Revenue"

    result = extractor.extract(structural_text, doc_type="tabular_data", strategy="structural_summary")

    assert result.summary != ""
    assert len(http_client.requests) == 1   # single call, no map-reduce

def test_extract_tabular_doc_type_alone_triggers_structural_path():
    """doc_type='tabular_data' implies structural path even without strategy kwarg."""
    http_client = FakeHttpClient(_make_tabular_payload())
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
    result = extractor.extract("Sheet 1: 100 rows", doc_type="tabular_data")
    assert len(http_client.requests) == 1
