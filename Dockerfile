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

# Install dependencies first for better layer caching, then the package itself.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e ".[dev]"

# Remaining project files (alembic, tests, etc.).
COPY . .

# Run as a non-root user.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-c", "from lofc.config import settings; print(settings)"]
