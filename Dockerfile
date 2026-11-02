# Pinned to 3.11 for the broadest data-science wheel coverage.
# (The host machine runs 3.14; irrelevant inside the container.)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# psycopg2 / scientific wheels occasionally need a compiler at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies BEFORE the source: this layer depends only on pyproject.toml, so a code-only
# deploy reuses it instead of reinstalling every package (deploy 2.5 min -> seconds).
# The editable install needs the package directory to exist; a stub stands in, and the real
# src/ copied below replaces it (the install points at /app/src/lofc, not at the stub's files).
COPY pyproject.toml README.md ./
RUN mkdir -p src/lofc && touch src/lofc/__init__.py \
    && pip install --upgrade pip && pip install -e ".[dev]"

# Run as a non-root user. /app is still tiny here, so this chown is instant; the project
# files below arrive already owned by appuser instead of a recursive chown of everything.
RUN useradd --create-home appuser && chown -R appuser:appuser /app

# Source and remaining project files (alembic, tests, etc.).
COPY --chown=appuser:appuser . .
USER appuser

CMD ["python", "-c", "from lofc.config import settings; print(settings)"]
