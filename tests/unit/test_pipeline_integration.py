import pytest

from nexus.repository import InMemoryRepository
from nexus.services.file_gate import FileGate, GateVerdict
from nexus.services.knowledge_extractor import ExtractedKnowledge
from nexus.services.pipeline import SemanticPipeline


class FakeCloudreveClient:
    def get_file_content_sync(self, uri):
        assert uri == "cloudreve://my/demo.md"
        return b"# Demo API architecture\n\nKnowledge Nexus semantic pipeline schema."


class FakeExtractor:
    def __init__(self):
        self.calls = []

    def get_document_type_suggestions(self, filename, text_preview):
        return "technical_doc"

    def extract(self, text, doc_type, ontology=None, strategy="llm_extract"):
        self.calls.append({"text": text, "doc_type": doc_type, "strategy": strategy})
        # doc_type is now set by DocumentClassifier, not FakeExtractor
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
    extractor = FakeExtractor()
    pipeline.knowledge_extractor = extractor

    result = pipeline.process_file("cloudreve://my/demo.md", requested_by="user-1")

    assert result.success is True
    document = repository.get_document("cloudreve://my/demo.md")
    assert document is not None
    assert document.summary == "Demo summary"
    assert document.tags == ["demo", "semantic"]
    assert document.entities == ["Nexus"]
    assert document.requested_by == "user-1"
    assert document.chunks
    assert result.kgraph_context["source_id"] == "cloudreve://my/demo.md"
    assert result.kgraph_context["classification"]["doc_type"] == "technical_doc"
    assert extractor.calls[0]["text"].startswith("[doc_")


class MixedSignalCloudreveClient:
    def get_file_content_sync(self, uri):
        return (
            b"Lunch logistics and office notice.\n\n"
            b"AuthService calls POST /api/users and stores profiles in PostgreSQL.\n\n"
            b"Weather update for the office.\n\n"
            b"DataPipeline depends on Redis and returns UserProfile."
        )


def test_semantic_pipeline_extracts_from_filtered_kgraph_context():
    repository = InMemoryRepository()
    pipeline = SemanticPipeline(
        cloudreve_token=None,
        repository=repository,
        enable_neo4j=False,
        enable_milvus=False,
    )
    pipeline.cloudreve_client = MixedSignalCloudreveClient()
    extractor = FakeExtractor()
    pipeline.knowledge_extractor = extractor

    result = pipeline.process_file("cloudreve://my/api_design.md", requested_by="user-1")

    extracted_text = extractor.calls[0]["text"]
    assert result.success is True
    assert "AuthService" in extracted_text
    assert "DataPipeline" in extracted_text
    assert "Lunch logistics" not in extracted_text
    assert "Weather update" not in extracted_text
    assert result.kgraph_context["sections"]



# ---------------------------------------------------------------------------
# FileGate unit tests
# ---------------------------------------------------------------------------

class TestFileGate:
    def setup_method(self):
        self.gate = FileGate()

    @pytest.mark.parametrize("filename", [
        "report.pdf", "notes.md", "readme.txt", "data.csv",
        "config.json", "schema.yaml", "page.html", "doc.docx",
        # Excel now handled via structural-summary extraction
        "spreadsheet.xlsx", "data.xls", "workbook.xlsm",
    ])
    def test_processable_extensions(self, filename):
        result = self.gate.check(filename)
        assert result.verdict == GateVerdict.PROCESSABLE
        assert result.should_process is True
        assert result.permanent_skip is False

    @pytest.mark.parametrize("filename", [
        "photo.jpg", "avatar.png", "banner.gif", "clip.mp4",
        "song.mp3", "archive.zip", "backup.tar", "app.exe",
        "disk.iso", "icon.svg",
    ])
    def test_binary_extensions_are_permanently_skipped(self, filename):
        result = self.gate.check(filename)
        assert result.verdict == GateVerdict.SKIPPED
        assert result.should_process is False
        assert result.permanent_skip is True

    @pytest.mark.parametrize("filename", [
        "slides.pptx", "email.eml",
    ])
    def test_unsupported_extensions_are_skipped_but_not_permanent(self, filename):
        result = self.gate.check(filename)
        assert result.verdict == GateVerdict.UNSUPPORTED
        assert result.should_process is False
        assert result.permanent_skip is False

    def test_no_extension_is_unsupported(self):
        result = self.gate.check("Makefile")
        assert result.verdict == GateVerdict.UNSUPPORTED

    def test_unknown_extension_is_unsupported(self):
        result = self.gate.check("something.xyz123")
        assert result.verdict == GateVerdict.UNSUPPORTED

    def test_case_insensitive_extension_matching(self):
        assert self.gate.check("PHOTO.JPG").verdict == GateVerdict.SKIPPED
        assert self.gate.check("Report.PDF").verdict == GateVerdict.PROCESSABLE


# ---------------------------------------------------------------------------
# Pipeline gate integration test
# ---------------------------------------------------------------------------

def test_pipeline_skips_image_without_downloading():
    """process_file() should return skipped=True for .jpg without calling the client."""

    class NeverCalledClient:
        def get_file_content_sync(self, uri):
            raise AssertionError("Client should not be called for skipped files")

    repository = InMemoryRepository()
    pipeline = SemanticPipeline(
        cloudreve_token=None,
        repository=repository,
        enable_neo4j=False,
        enable_milvus=False,
    )
    pipeline.cloudreve_client = NeverCalledClient()

    result = pipeline.process_file("cloudreve://my/photo.jpg")

    assert result.skipped is True
    assert result.success is True
    assert result.stage == "gate"
    assert result.skip_reason is not None
    # No document should be stored for skipped files
    assert repository.get_document("cloudreve://my/photo.jpg") is None
