#!/usr/bin/env bash
set -euo pipefail

# FitBites Production Deploy Script
# Usage: ./scripts/deploy.sh [railway|render|docker]

PLATFORM="${1:-docker}"

echo "🚀 FitBites Deploy — Platform: $PLATFORM"

# Pre-flight checks
echo "📋 Running pre-flight checks..."

# 1. Tests must pass
echo "  Running tests..."
python3 -m pytest tests/ -q --tb=short || {
    echo "❌ Tests failed. Fix before deploying."
    exit 1
}
echo "  ✅ Tests pass"

# 2. Check .env exists (for docker deploys)
if [ "$PLATFORM" = "docker" ]; then
    if [ ! -f .env ]; then
        echo "❌ No .env file found. Copy .env.example and fill in values."
        exit 1
    fi
    echo "  ✅ .env found"
fi

# 3. Run Alembic migrations check
echo "  Checking migrations..."
if command -v alembic &> /dev/null; then
    alembic check 2>/dev/null && echo "  ✅ Migrations up to date" || echo "  ⚠️  Run 'alembic upgrade head' after deploy"
fi

echo ""

case "$PLATFORM" in
    docker)
        echo "🐳 Building and deploying with Docker Compose..."
        docker compose -f docker-compose.prod.yml up -d --build
        echo "⏳ Waiting for health check..."
        sleep 10
        curl -sf http://localhost:8000/health && echo "" && echo "✅ Deployed and healthy!" || echo "❌ Health check failed"
        ;;
    railway)
        echo "🚂 Deploying to Railway..."
        if ! command -v railway &> /dev/null; then
            echo "❌ Railway CLI not installed. Run: npm i -g @railway/cli"
            exit 1
        fi
        railway up
        echo "✅ Deployed to Railway"
        ;;
    render)
        echo "🎨 Deploying to Render..."
        echo "Push to main branch — Render auto-deploys from render.yaml"
        git push origin main
        echo "✅ Pushed to main — Render will deploy automatically"
        ;;
    *)
        echo "❌ Unknown platform: $PLATFORM"
        echo "Usage: ./scripts/deploy.sh [docker|railway|render]"
        exit 1
        ;;
esac
