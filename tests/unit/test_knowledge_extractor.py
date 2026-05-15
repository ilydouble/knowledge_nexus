import json

from nexus.services.knowledge_extractor import KnowledgeExtractor


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
