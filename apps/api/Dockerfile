# Dev image. src/ and alembic/ are bind-mounted by compose.override.yml so
# edits reload without a rebuild; see Dockerfile.prod for the deployed one.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# The lockfile, and `--frozen` so it is actually obeyed. Without both, `uv
# sync` resolves fresh against pyproject's loose constraints at build time
# and the committed lock is never used by any image — two people building a
# month apart get different dependency trees, and a transitive break lands
# with no repo change to blame. apps/web has always done this correctly
# (`pnpm install --frozen-lockfile`); this is the API catching up.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

# `--no-sync`: run what the image already installed, and never reach for the
# network at boot. Without it `uv run` re-syncs the project environment every
# time a container starts — which pulled the *dev* dependencies straight back
# into an image built with `--no-dev`, and meant a production container could
# not start at all on a host that could not reach PyPI. A deploy that needs
# the internet to boot is a deploy that is down when PyPI is.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
