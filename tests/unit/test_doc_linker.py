import json

from nexus.models import SemanticDocument, TextChunk
from nexus.repositories.memory import InMemoryRepository
from nexus.services.doc_linker import DocLinker


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


def _add_document(repository, uri, summary, tags, entities):
    return repository.add_document(
        SemanticDocument(
            uri=uri,
            summary=summary,
            tags=tags,
            entities=entities,
            chunks=[TextChunk(id=f"{uri}#chunk-1", text=summary, index=1)],
            requested_by="user-1",
        )
    )


def test_doc_linker_creates_links_for_documents_with_shared_entities_without_llm():
    repository = InMemoryRepository()
    _add_document(repository, "cloudreve://my/a.md", "API design for AuthService", ["api"], ["AuthService", "PostgreSQL"])
    _add_document(repository, "cloudreve://my/b.md", "Deployment notes for AuthService", ["ops"], ["AuthService", "Redis"])
    _add_document(repository, "cloudreve://my/c.md", "HR onboarding", ["hr"], ["PeopleOps"])

    results = DocLinker(repository=repository, api_key=None).find_and_link_all(min_shared_entities=1)

    assert len(results) == 1
    assert results[0].uri_a == "cloudreve://my/a.md"
    assert results[0].uri_b == "cloudreve://my/b.md"
    assert results[0].relation == "相似"
    assert results[0].shared_entities == ["AuthService"]
    stored = repository.list_links()
    assert len(stored) == 1
    assert stored[0].created_by == "doc_linker"
    assert stored[0].note == "Shared entities: AuthService"


def test_doc_linker_uses_llm_to_type_document_relation():
    repository = InMemoryRepository()
    _add_document(repository, "cloudreve://my/base.md", "API baseline design", ["api"], ["AuthService"])
    _add_document(repository, "cloudreve://my/extension.md", "Adds retry details to API baseline", ["api"], ["AuthService"])
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "relation": "扩展",
                            "confidence": 0.84,
                            "reasoning": "补充接口细节",
                            "direction": "a_to_b",
                        }
                    )
                }
            }
        ]
    }
    http_client = FakeHttpClient(payload)

    results = DocLinker(repository=repository, api_key="test-key", http_client=http_client).find_and_link_all()

    assert len(results) == 1
    assert results[0].relation == "扩展"
    assert results[0].confidence == 0.84
    assert results[0].direction == "a_to_b"
    assert http_client.requests[0]["headers"]["Authorization"] == "Bearer test-key"
