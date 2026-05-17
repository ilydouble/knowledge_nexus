from __future__ import annotations

from fastapi import FastAPI

from nexus.app_factory import create_application
from nexus.repositories.base import NexusRepository
from nexus.settings import Settings


def create_app(repository: NexusRepository | None = None, settings: Settings | None = None) -> FastAPI:
    return create_application(repository=repository, settings=settings)


app = create_app()

