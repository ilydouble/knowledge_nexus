from __future__ import annotations

import asyncio
import json
import logging

from nexus.cloudreve.client import CloudreveClient
from nexus.repository import InMemoryRepository
from nexus.services.events import FileEventHandler
from nexus.settings import Settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexus.worker")


async def watch_cloudreve_events() -> None:
    repository = InMemoryRepository()
    handler = FileEventHandler(repository)
    settings = Settings.from_env()
    client = CloudreveClient(token=settings.cloudreve_token)
    async for event in client.iter_file_events(client_id=settings.cloudreve_client_id):
        try:
            payload = json.loads(event["raw"])
        except json.JSONDecodeError:
            logger.warning("Ignoring malformed Cloudreve event: %s", event)
            continue
        events = payload if isinstance(payload, list) else [payload]
        jobs = handler.handle_events(events)
        if jobs:
            logger.info("Queued %s ingestion job(s)", len(jobs))


def main() -> None:
    asyncio.run(watch_cloudreve_events())


if __name__ == "__main__":
    main()
