FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY nexus ./nexus
COPY apps/api ./apps/api

RUN pip install --no-cache-dir fastapi httpx neo4j "psycopg[binary]" "pymilvus>=2.3,<2.4" pydantic uvicorn

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
