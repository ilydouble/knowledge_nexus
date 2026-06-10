def test_knowledge_os_exposes_canonical_layered_imports():
    from knowledge_os.application.services import CandidateExtractionService
    from knowledge_os.domain.models import CandidateExtractionRequest
    from knowledge_os.infrastructure.memory_store import InMemoryKnowledgeOSStore
    from knowledge_os.infrastructure.postgres_store import PostgresKnowledgeOSStore

    assert CandidateExtractionService.__name__ == "CandidateExtractionService"
    assert CandidateExtractionRequest.__name__ == "CandidateExtractionRequest"
    assert InMemoryKnowledgeOSStore.__name__ == "InMemoryKnowledgeOSStore"
    assert PostgresKnowledgeOSStore.__name__ == "PostgresKnowledgeOSStore"


def test_knowledge_os_exposes_canonical_interface_registration_imports():
    from knowledge_os.interfaces.api import register_knowledge_os_api
    from knowledge_os.interfaces.mcp import register_knowledge_os_tools

    assert register_knowledge_os_api.__name__ == "register_knowledge_os_api"
    assert register_knowledge_os_tools.__name__ == "register_knowledge_os_tools"



