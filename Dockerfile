FROM python:3.12-slim AS base

# Cache bust: 2026-02-28 04:55 - Force rebuild (yt-dlp shutil.which fix)
# Security: don't run as root
RUN groupadd -r fitbites && useradd -r -g fitbites -d /app fitbites

# Install ffmpeg and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (needed by yt-dlp for YouTube EJS signature solving)
RUN curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip \
    && unzip /tmp/deno.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

WORKDIR /app

# Copy application code
COPY . .

# Install Python deps + yt-dlp
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev]" && \
    pip install --no-cache-dir yt-dlp

# Download yt-dlp EJS challenge solver scripts
RUN yt-dlp --update-components 2>/dev/null || true

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R fitbites:fitbites /app

USER fitbites

EXPOSE 8000

# Default CMD (Railway overrides via railway.toml startCommand)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
