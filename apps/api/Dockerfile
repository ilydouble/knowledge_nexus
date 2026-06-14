FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required by pdfplumber / python-docx
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first so Docker can cache the dependency layer
COPY pyproject.toml ./

# Copy all source packages the API depends on
COPY core/ ./core/
COPY knowledge_os/ ./knowledge_os/
COPY apps/ ./apps/

# Install all declared dependencies from pyproject.toml (includes minio,
# pdfplumber, python-docx, pymilvus, mcp, pyyaml, etc.)
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
