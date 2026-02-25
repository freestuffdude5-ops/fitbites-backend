FROM python:3.12-slim AS base

# Security: don't run as root
RUN groupadd -r fitbites && useradd -r -g fitbites -d /app fitbites

WORKDIR /app

# Install deps first (cached layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir \
        fastapi uvicorn[standard] pydantic[email] sqlalchemy aiosqlite asyncpg \
        anthropic httpx python-dotenv apscheduler python-multipart

# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R fitbites:fitbites /app

USER fitbites

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8000/health'); assert r.status_code==200" || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--loop", "uvloop", "--http", "httptools"]
