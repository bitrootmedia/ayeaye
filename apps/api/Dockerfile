# Dev image. src/ and alembic/ are bind-mounted by compose.override.yml so
# edits reload without a rebuild; see Dockerfile.prod for the deployed one.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
