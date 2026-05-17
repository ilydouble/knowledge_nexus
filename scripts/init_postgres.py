from __future__ import annotations

from nexus.repositories.postgres import initialize_postgres_schema
from nexus.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    initialize_postgres_schema(settings.database_url)
    print("Knowledge Nexus Postgres schema initialized.")


if __name__ == "__main__":
    main()

