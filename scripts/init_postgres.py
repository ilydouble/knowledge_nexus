from __future__ import annotations

from core.repositories.postgres import initialize_postgres_schema
from core.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    initialize_postgres_schema(settings.database_url)
    print("Knowledge Nexus Postgres schema initialized.")


if __name__ == "__main__":
    main()

