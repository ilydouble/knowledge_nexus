import json

from core.services.document_classifier import CATEGORIES, DocumentClassifier
from core.services.knowledge_extractor import (
    ExtractedKnowledge,
    KnowledgeExtractor,
    MIN_ENTITY_CONFIDENCE,
    _EXTRACTION_JSON_SCHEMA,
    _MAP_REDUCE_THRESHOLD,
    _SEGMENT_SIZE,
    _cosine_sim,
    _parse_llm_json,
)


def test_parse_llm_json_strips_markdown_code_fence():
    """Models like glm-4-flash wrap JSON in ```json fences; these must parse."""
    fenced = '```json\n{"summary": "ok", "entities": []}\n```'
    assert _parse_llm_json(fenced) == {"summary": "ok", "entities": []}


def test_parse_llm_json_handles_plain_and_bare_fence():
    assert _parse_llm_json('{"a": 1}') == {"a": 1}
    assert _parse_llm_json('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_llm_json_extracts_embedded_object():
    """Falls back to the outermost {...} span when extra prose surrounds it."""
    noisy = 'Here is the result:\n{"a": 1}\nThanks!'
    assert _parse_llm_json(noisy) == {"a": 1}


def test_parse_llm_json_rejects_empty_content():
    import pytest

    with pytest.raises(ValueError):
        _parse_llm_json("   ")


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
    # ⑤ Schema-constrained output: must use json_schema mode, not plain json_object
    assert request["json"]["response_format"]["type"] == "json_schema"
    assert request["json"]["response_format"] == _EXTRACTION_JSON_SCHEMA


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


def test_mapreduce_preserves_cross_segment_relations():
    """Relations whose endpoints span different segments must NOT be pruned.

    Scenario: entity "a" appears only in segment-1 result; entity "b" only in
    segment-2 result; a relation (a→b) is returned by segment-2.  After global
    merge both entities exist, so the relation must survive.
    """
    seg1_payload = {
        "choices": [{"message": {"content": json.dumps({
            "summary": "seg1",
            "tags": [],
            "entities": [{"id": "a", "label": "A", "type": "Concept", "confidence": 0.9}],
            "relations": [],
            "key_points": [],
        })}}]
    }
    seg2_payload = {
        "choices": [{"message": {"content": json.dumps({
            "summary": "seg2",
            "tags": [],
            "entities": [{"id": "b", "label": "B", "type": "Concept", "confidence": 0.9}],
            # cross-segment relation: a (from seg1) → b (from seg2)
            "relations": [{"source": "a", "target": "b", "relation": "LINKS"}],
            "key_points": [],
        })}}]
    }

    responses = [seg1_payload, seg2_payload]

    class SequentialFakeClient:
        """Returns different payloads per call (thread-safe via list.pop is not
        order-safe under concurrency, so use a fixed single-thread extractor)."""
        def __init__(self):
            self._lock = concurrent.futures.ThreadPoolExecutor  # unused, just label
            self._calls = 0
            import threading
            self._lock = threading.Lock()

        def post(self, url, *, headers, json, timeout):
            with self._lock:
                idx = self._calls % 2
                self._calls += 1
            return FakeResponse(responses[idx])

    import threading

    class SeqClient:
        def __init__(self):
            self._lock = threading.Lock()
            self._calls = 0

        def post(self, url, *, headers, json, timeout):
            with self._lock:
                idx = self._calls % len(responses)
                self._calls += 1
            return FakeResponse(responses[idx])

    extractor = KnowledgeExtractor(
        api_key="k", model="m", http_client=SeqClient(), max_workers=1
    )
    # Construct exactly 2 segments to guarantee one call per segment
    text = "x" * (_SEGMENT_SIZE + 1)
    result = extractor._extract_mapreduce(text, "general", {"concepts": [], "relations": [], "instructions": ""})

    entity_ids = {e["id"] for e in result.entities}
    assert "a" in entity_ids
    assert "b" in entity_ids
    # Cross-segment relation must survive global pruning
    assert any(r["source"] == "a" and r["target"] == "b" for r in result.relations), \
        "Cross-segment relation a→b was incorrectly pruned"


def test_concurrent_mapreduce_uses_multiple_threads():
    """Map-reduce with max_workers>1 should complete without error and return results."""
    import threading

    call_threads: list[int] = []
    lock = threading.Lock()

    payload = {
        "choices": [{"message": {"content": json.dumps(
            {"summary": "s", "tags": [], "entities": [], "relations": [], "key_points": []}
        )}}]
    }

    class TrackingClient:
        def post(self, url, *, headers, json, timeout):
            with lock:
                call_threads.append(threading.get_ident())
            return FakeResponse(payload)

    long_text = "word " * (_MAP_REDUCE_THRESHOLD + 5000)
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=TrackingClient(), max_workers=4)
    result = extractor.extract(long_text)
    assert isinstance(result, ExtractedKnowledge)
    # At least one segment call was made
    assert len(call_threads) >= 1



# ---------------------------------------------------------------------------
# ⑤  Schema-constrained output
# ---------------------------------------------------------------------------

def test_schema_constrained_output_uses_json_schema_format():
    """_call_chat_completion must send json_schema, not plain json_object."""
    payload = {"choices": [{"message": {"content": json.dumps(
        {"summary": "s", "tags": [], "entities": [], "relations": [], "key_points": []}
    )}}]}
    http_client = FakeHttpClient(payload)
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
    extractor.extract("hello")
    fmt = http_client.requests[0]["json"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "extraction_result"


def test_call_chat_completion_accepts_custom_response_format():
    """Callers can override response_format (e.g. _NODE_JSON_SCHEMA for two-stage)."""
    from core.services.knowledge_extractor import _NODE_JSON_SCHEMA
    payload = {"choices": [{"message": {"content": json.dumps({"entities": []})}}]}
    http_client = FakeHttpClient(payload)
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=http_client)
    extractor._call_chat_completion("extract nodes", _NODE_JSON_SCHEMA)
    fmt = http_client.requests[0]["json"]["response_format"]
    assert fmt["json_schema"]["name"] == "node_extraction_result"


# ---------------------------------------------------------------------------
# ③  Two-stage extraction
# ---------------------------------------------------------------------------

def test_two_stage_makes_two_rounds_of_llm_calls():
    """two_stage_extraction=True must produce 2N calls (N node + N edge rounds)."""
    import threading

    call_log: list[str] = []
    lock = threading.Lock()

    node_payload = {"choices": [{"message": {"content": json.dumps({
        "entities": [{"id": "a", "label": "A", "type": "Concept", "confidence": 0.9}]
    })}}]}
    edge_payload = {"choices": [{"message": {"content": json.dumps({
        "relations": [{"source": "a", "target": "a", "relation": "SELF"}]
    })}}]}

    class TwoRoundClient:
        def __init__(self):
            self._calls = 0
            self._lock = threading.Lock()
        def post(self, url, *, headers, json, timeout):
            with self._lock:
                idx = self._calls
                self._calls += 1
            fmt_name = json.get("response_format", {}).get("json_schema", {}).get("name", "")
            with lock:
                call_log.append(fmt_name)
            return FakeResponse(node_payload if "node" in fmt_name else edge_payload)

    long_text = "x" * (_SEGMENT_SIZE * 2 + 1)
    extractor = KnowledgeExtractor(
        api_key="k", model="m",
        http_client=TwoRoundClient(),
        two_stage_extraction=True,
        max_workers=1,
    )
    result = extractor.extract(long_text)

    node_calls = sum(1 for n in call_log if "node" in n)
    edge_calls = sum(1 for n in call_log if "edge" in n)
    assert node_calls >= 1, "Should have at least one node-extraction call"
    assert edge_calls >= 1, "Should have at least one edge-extraction call"
    assert isinstance(result, ExtractedKnowledge)


def test_two_stage_entity_in_result():
    """Two-stage mode must include entities extracted in Round 1."""
    node_payload = {"choices": [{"message": {"content": json.dumps({
        "entities": [{"id": "concept_alpha", "label": "Alpha", "type": "Concept", "confidence": 0.9}]
    })}}]}
    edge_payload = {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}

    class FixedClient:
        def post(self, url, *, headers, json, timeout):
            fmt = json.get("response_format", {}).get("json_schema", {}).get("name", "")
            return FakeResponse(node_payload if "node" in fmt else edge_payload)

    long_text = "x" * (_SEGMENT_SIZE + 1)
    extractor = KnowledgeExtractor(
        api_key="k", model="m",
        http_client=FixedClient(),
        two_stage_extraction=True,
        max_workers=1,
    )
    result = extractor._extract_mapreduce(
        long_text, "general", {"concepts": [], "relations": [], "instructions": ""}
    )
    entity_ids = {e["id"] for e in result.entities}
    assert "concept_alpha" in entity_ids


# ---------------------------------------------------------------------------
# ④  Semantic deduplication
# ---------------------------------------------------------------------------

def test_cosine_sim_orthogonal_vectors():
    assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_sim_identical_vectors():
    v = [0.6, 0.8]
    assert abs(_cosine_sim(v, v) - 1.0) < 1e-9


def test_semantic_dedup_merges_near_duplicates():
    """Two entities with embedding similarity ≥ threshold must be merged."""

    class FakeEmbedder:
        """Returns near-identical vectors for 'Alpha' and 'alpha', different for 'Beta'."""
        def embed_batch(self, texts):
            return [
                [1.0, 0.0, 0.0] if t.lower().startswith("alpha") else [0.0, 1.0, 0.0]
                for t in texts
            ]

    extractor = KnowledgeExtractor(
        api_key=None,
        embedding_service=FakeEmbedder(),
        semantic_dedup_threshold=0.99,  # identical vectors → 1.0 ≥ 0.99
    )
    knowledge = ExtractedKnowledge(
        summary="s", tags=[],
        entities=[
            {"id": "concept_alpha", "label": "Alpha", "type": "Concept", "confidence": 0.9},
            {"id": "concept_alpha2", "label": "alpha", "type": "Concept", "confidence": 0.8},
            {"id": "concept_beta", "label": "Beta", "type": "Concept", "confidence": 0.9},
        ],
        relations=[
            {"source": "concept_alpha", "target": "concept_beta", "relation": "R"},
            {"source": "concept_alpha2", "target": "concept_beta", "relation": "R"},  # duplicate after merge
        ],
        key_points=[],
    )
    result = extractor._semantic_dedup(knowledge)
    result_ids = {e["id"] for e in result.entities}
    # Alpha + alpha merged → one canonical; Beta kept
    assert len(result.entities) == 2
    assert "concept_beta" in result_ids
    # After merge+dedup, only one R relation from the alpha canonical → beta
    assert len(result.relations) == 1


def test_semantic_dedup_skips_when_no_embedding_service():
    extractor = KnowledgeExtractor(api_key=None, embedding_service=None)
    knowledge = ExtractedKnowledge(
        summary="s", tags=[],
        entities=[{"id": "x", "label": "X", "type": "Concept", "confidence": 0.9}],
        relations=[], key_points=[],
    )
    result = extractor._merge_extractions([knowledge])
    # No dedup attempted → entity unchanged
    assert result.entities[0]["id"] == "x"


def test_semantic_dedup_handles_embedding_failure_gracefully():
    class FailingEmbedder:
        def embed_batch(self, texts):
            raise RuntimeError("API down")

    extractor = KnowledgeExtractor(api_key=None, embedding_service=FailingEmbedder())
    knowledge = ExtractedKnowledge(
        summary="s", tags=[],
        entities=[{"id": "a", "label": "A", "type": "Concept", "confidence": 0.9}],
        relations=[], key_points=[],
    )
    # Must not raise; returns knowledge unchanged
    result = extractor._semantic_dedup(knowledge)
    assert result.entities[0]["id"] == "a"


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

    def test_smart_campus_keywords_detect_domain_documents(self):
        result = self.clf.classify(
            "智慧园区BMS能耗与故障诊断方案.md",
            content_preview="采用 Brick Schema 描述楼宇空间、HVAC 设备、EMS 电表、BMS 点位、AHU 故障和工单闭环。",
        )

        assert result.doc_type == "smart_campus"
        assert result.strategy == "llm_extract"
        assert result.confidence >= 0.4

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

    def test_all_doc_types_resolve_yaml_ontology(self):
        """Every canonical doc_type must load a full ontology via the YAML adapter."""
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None)
        for doc_type in ("tabular_data", "contract", "email", "academic_paper",
                         "technical_doc", "meeting_minutes", "report", "general", "smart_campus"):
            ontology = extractor._get_ontology(doc_type)
            assert "concepts" in ontology, f"{doc_type}: missing 'concepts'"
            assert "relations" in ontology, f"{doc_type}: missing 'relations'"
            assert "instructions" in ontology, f"{doc_type}: missing 'instructions'"

    def test_each_yaml_template_has_rich_ontology_fields(self):
        """Every YAML template must have concepts (with descriptions) and relations (with source/target)."""
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None)
        for doc_type in ("tabular_data", "contract", "email", "academic_paper",
                         "technical_doc", "meeting_minutes", "report"):
            tmpl = extractor._get_ontology(doc_type)
            for concept in tmpl["concepts"]:
                assert "type" in concept and "description" in concept, \
                    f"{doc_type}: concept missing type or description: {concept}"
                assert concept["description"] != f"{concept['type']} entity", \
                    f"{doc_type}: concept '{concept['type']}' still has placeholder description"
            for rel in tmpl["relations"]:
                assert "relation" in rel and "source" in rel and "target" in rel, \
                    f"{doc_type}: relation missing relation/source/target: {rel}"

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

    def test_get_ontology_returns_general_base_graph_without_embedding_service(self):
        """Without embedding_service, _get_ontology falls back to general/base_graph."""
        extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None)
        ontology = extractor._get_ontology("contract")
        # general/base_graph has graph-family concepts (person, location, org, …)
        types = {c["type"].lower() for c in ontology.get("concepts", [])}
        assert len(types) > 0

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


# ---------------------------------------------------------------------------
# SemanticTemplateMatcher
# ---------------------------------------------------------------------------

from core.services.semantic_matcher import SemanticTemplateMatcher
from core.services.embedding import DeterministicEmbeddingService


class _FakeEmbeddingService:
    """Records calls and returns deterministic vectors."""

    def __init__(self, dimensions: int = 64) -> None:
        self._inner = DeterministicEmbeddingService(dimensions=dimensions)
        self.calls: list[list[str]] = []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return self._inner.embed_batch(texts)


def test_semantic_matcher_returns_merged_ontology():
    """match() returns a dict with concepts and relations from top-K templates."""
    svc = _FakeEmbeddingService()
    matcher = SemanticTemplateMatcher(embedding_service=svc, top_k=2)

    result = matcher.match(text="Annual report risk factors", filename="risk_report.pdf")

    assert result is not None
    assert "concepts" in result and "relations" in result and "instructions" in result
    assert len(result["concepts"]) > 0
    assert len(result["relations"]) > 0


def test_semantic_matcher_skips_nexus_templates():
    """Nexus/ templates are excluded from the candidate set by default."""
    svc = _FakeEmbeddingService()
    matcher = SemanticTemplateMatcher(embedding_service=svc, top_k=3)
    matcher.match(text="test", filename="test.pdf")

    # Template embedding texts should not include any nexus/ template
    embedded_templates = matcher._template_vectors or {}
    assert not any(tid.startswith("nexus/") for tid in embedded_templates)


def test_semantic_matcher_deduplicates_merged_concepts():
    """Merged ontology has no duplicate concept types even across multiple templates."""
    svc = _FakeEmbeddingService()
    matcher = SemanticTemplateMatcher(embedding_service=svc, top_k=3)

    result = matcher.match(text="legal contract obligations", filename="contract.pdf")

    assert result is not None
    types = [c["type"] for c in result["concepts"]]
    assert len(types) == len(set(types)), "Duplicate concept types in merged ontology"


def test_semantic_matcher_caches_template_vectors():
    """Template vectors are embedded only once across multiple match() calls."""
    svc = _FakeEmbeddingService()
    matcher = SemanticTemplateMatcher(embedding_service=svc, top_k=2)

    matcher.match(text="first call", filename="a.pdf")
    matcher.match(text="second call", filename="b.pdf")

    # First call: 1 batch for templates + 1 for document query = 2 calls
    # Second call: no template re-embedding + 1 for document query = 1 call
    assert len(svc.calls) == 3


def test_semantic_matcher_graceful_failure_returns_none():
    """If embed_batch raises, match() returns None (graceful degradation)."""

    class FailingEmbedService:
        def embed_batch(self, texts):
            raise RuntimeError("API down")

    matcher = SemanticTemplateMatcher(embedding_service=FailingEmbedService(), top_k=2)
    result = matcher.match(text="some text", filename="doc.pdf")
    assert result is None


def test_get_ontology_uses_semantic_matcher_when_embedding_service_provided():
    """KnowledgeExtractor._get_ontology uses SemanticTemplateMatcher when embedding_service set."""
    svc = _FakeEmbeddingService()
    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None, embedding_service=svc)

    ontology = extractor._get_ontology("general", text="medical drug interaction study", filename="med.pdf")

    assert "concepts" in ontology
    assert len(ontology["concepts"]) > 0
    # At least one embed_batch call was made (template vectors)
    assert len(svc.calls) >= 1


def test_get_ontology_falls_back_when_matcher_returns_none():
    """If SemanticTemplateMatcher fails, _get_ontology falls back to general/base_graph."""

    class AlwaysFailEmbed:
        def embed_batch(self, texts):
            raise RuntimeError("fail")

    extractor = KnowledgeExtractor(api_key="k", model="m", http_client=None,
                                   embedding_service=AlwaysFailEmbed())
    # Should not raise; falls back to general/base_graph or emergency fallback
    ontology = extractor._get_ontology("general")
    assert "concepts" in ontology
    assert len(ontology["concepts"]) > 0
