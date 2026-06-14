from core.models import KnowledgeLayer, KnowledgeLink
from core.repositories.base import NexusRepository
from core.repositories.memory import InMemoryRepository


def exercise_repository_contract(repository: NexusRepository):
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

    # delete_document is a no-op in the new architecture but must exist
    repository.delete_document("cloudreve://my/a.md")


def test_in_memory_repository_satisfies_repository_contract():
    exercise_repository_contract(InMemoryRepository())
