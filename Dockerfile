FROM python:3.12-slim AS base

# Cache bust: 2026-02-24 22:09 - psycopg2-binary fix
# Security: don't run as root
RUN groupadd -r fitbites && useradd -r -g fitbites -d /app fitbites

WORKDIR /app

# Install deps first (updated 2026-02-24 with psycopg2-binary)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir \
        fastapi uvicorn[standard] pydantic[email] sqlalchemy aiosqlite asyncpg psycopg2-binary \
        anthropic httpx python-dotenv apscheduler python-multipart sentry-sdk[fastapi]

# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R fitbites:fitbites /app

USER fitbites

EXPOSE 8000

# No CMD - let railway.toml handle the start command
