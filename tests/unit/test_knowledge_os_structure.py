def test_knowledge_os_exposes_canonical_layered_imports():
    from nexus.knowledge_os.application.services import CandidateExtractionService
    from nexus.knowledge_os.domain.models import CandidateExtractionRequest
    from nexus.knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
    from nexus.knowledge_os.infrastructure.postgres_store import PostgresKnowledgeOSStore

    assert CandidateExtractionService.__name__ == "CandidateExtractionService"
    assert CandidateExtractionRequest.__name__ == "CandidateExtractionRequest"
    assert InMemoryKnowledgeOSStore.__name__ == "InMemoryKnowledgeOSStore"
    assert PostgresKnowledgeOSStore.__name__ == "PostgresKnowledgeOSStore"
