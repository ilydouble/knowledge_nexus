"""External interface adapters for Knowledge OS."""

from nexus.knowledge_os.interfaces.api import register_knowledge_os_api
from nexus.knowledge_os.interfaces.mcp import register_knowledge_os_tools

__all__ = [
    "register_knowledge_os_api",
    "register_knowledge_os_tools",
]
