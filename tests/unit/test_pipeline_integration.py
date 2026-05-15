from nexus.repository import InMemoryRepository
from nexus.services.knowledge_extractor import ExtractedKnowledge
from nexus.services.pipeline import SemanticPipeline


class FakeCloudreveClient:
    def get_file_content_sync(self, uri):
        assert uri == "cloudreve://my/demo.md"
        return b"# Demo\n\nKnowledge Nexus semantic pipeline."


class FakeExtractor:
    def get_document_type_suggestions(self, filename, text_preview):
        return "technical_doc"

    def extract(self, text, doc_type):
        assert doc_type == "technical_doc"
        return ExtractedKnowledge(
            summary="Demo summary",
            tags=["demo", "semantic"],
            entities=[{"id": "project_nexus", "label": "Nexus", "type": "Project"}],
            relations=[],
            key_points=[],
        )


def test_semantic_pipeline_stores_processed_document_in_repository():
    repository = InMemoryRepository()
    pipeline = SemanticPipeline(
        cloudreve_token=None,
        repository=repository,
        enable_neo4j=False,
        enable_milvus=False,
    )
    pipeline.cloudreve_client = FakeCloudreveClient()
    pipeline.knowledge_extractor = FakeExtractor()

    result = pipeline.process_file("cloudreve://my/demo.md", requested_by="user-1")

    assert result.success is True
    document = repository.get_document("cloudreve://my/demo.md")
    assert document is not None
    assert document.summary == "Demo summary"
    assert document.tags == ["demo", "semantic"]
    assert document.entities == ["Nexus"]
    assert document.requested_by == "user-1"
    assert document.chunks
