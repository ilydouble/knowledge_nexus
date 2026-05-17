from nexus.models import KnowledgeLayer
from nexus.repository import InMemoryRepository
from nexus.services.autolinker import AutoLinker
from nexus.services.semantic import SemanticProcessor, TextParser


def test_text_parser_extracts_chunks_summary_tags_and_entities():
    parser = TextParser(chunk_size=40)

    document = parser.parse(
        uri="cloudreve://my/infrared.md",
        content="Infrared sensor project uses thermal calibration. Infrared sensor overheating resembles refrigerator heat.",
    )

    assert document.uri == "cloudreve://my/infrared.md"
    assert document.summary.startswith("Infrared sensor project")
    assert "infrared" in document.tags
    assert "Infrared" in document.entities
    assert len(document.chunks) > 1


def test_semantic_processor_indexes_document_as_graph_node():
    repository = InMemoryRepository()
    processor = SemanticProcessor(repository)

    document = processor.index_text(
        uri="cloudreve://my/infrared.md",
        content="Infrared sensor project uses thermal calibration.",
        requested_by="user-1",
    )

    nodes, _ = repository.graph()
    indexed = next(node for node in nodes if node.uri == document.uri)
    assert indexed.summary == document.summary
    assert indexed.properties["tags"] == document.tags


def test_autolinker_suggests_related_file_by_shared_tags():
    repository = InMemoryRepository()
    processor = SemanticProcessor(repository)
    processor.index_text("cloudreve://my/a.md", "Infrared sensor thermal project.", "user-1")
    processor.index_text("cloudreve://my/b.md", "Thermal sensor calibration notes.", "user-1")

    suggestions = AutoLinker(repository).suggest("cloudreve://my/a.md")

    assert suggestions
    assert suggestions[0].target_uri == "cloudreve://my/b.md"
    assert suggestions[0].layer == KnowledgeLayer.L3

