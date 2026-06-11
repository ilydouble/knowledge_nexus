from core.models import IngestionJob, KnowledgeLayer, KnowledgeLink, SemanticDocument, TextChunk
from core.repositories.base import NexusRepository
from core.repositories.memory import InMemoryRepository


def exercise_repository_contract(repository: NexusRepository):
    job = repository.add_job(IngestionJob(uri="cloudreve://my/a.md", requested_by="user-1"))
    assert repository.get_job(job.id) == job

    document = repository.add_document(
        SemanticDocument(
            uri="cloudreve://my/a.md",
            summary="Infrared sensor notes",
            tags=["infrared", "sensor"],
            entities=["Infrared"],
            chunks=[TextChunk(id="chunk-1", text="Infrared sensor notes", index=1)],
            requested_by="user-1",
        )
    )
    assert repository.get_document(document.uri) == document
    assert repository.list_documents() == [document]

    link = repository.add_link(
        KnowledgeLink(
            source_uri="cloudreve://my/a.md",
            target_uri="cloudreve://my/b.md",
            relation="RELATED_TO",
            layer=KnowledgeLayer.L3,
            owner_scope="user:user-1",
            source_file_uri="cloudreve://my/a.md",
            visibility="private",
            created_by="user-1",
        )
    )
    assert repository.list_links() == [link]

    nodes, edges = repository.graph()
    assert any(node.uri == "cloudreve://my/a.md" for node in nodes)
    assert edges[0].relation == "RELATED_TO"


def test_in_memory_repository_satisfies_repository_contract():
    exercise_repository_contract(InMemoryRepository())

