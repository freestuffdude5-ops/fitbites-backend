FROM python:3.12-slim AS base

# Cache bust: 2026-02-24 22:09 - psycopg2-binary fix
# Security: don't run as root
RUN groupadd -r fitbites && useradd -r -g fitbites -d /app fitbites

WORKDIR /app

# Copy application code
COPY . .

# Install deps
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev]"

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R fitbites:fitbites /app

USER fitbites

EXPOSE 8000

# Default CMD (Railway overrides via railway.toml startCommand)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
