from nexus.repository import InMemoryRepository
from nexus.services.events import FileEventHandler


def test_file_event_handler_enqueues_create_and_update_events():
    repository = InMemoryRepository()
    handler = FileEventHandler(repository)

    jobs = handler.handle_events(
        [
            {"type": "create", "to": "cloudreve://my/a.md"},
            {"type": "update", "uri": "cloudreve://my/b.md"},
            {"type": "delete", "from": "cloudreve://my/c.md"},
        ],
        requested_by="user-1",
    )

    assert [job.uri for job in jobs] == ["cloudreve://my/a.md", "cloudreve://my/b.md"]
    assert all(job.status == "pending" for job in jobs)

