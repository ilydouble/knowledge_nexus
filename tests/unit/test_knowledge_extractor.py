import json

from nexus.services.knowledge_extractor import (
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
