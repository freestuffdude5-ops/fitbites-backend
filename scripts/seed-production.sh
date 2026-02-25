#!/bin/bash
# Seed production database with initial recipes
# Run this ONCE after deploying to Railway to populate the database
# Usage: ./scripts/seed-production.sh [RAILWAY_DATABASE_URL]

set -e

PROD_DB_URL="$1"

if [ -z "$PROD_DB_URL" ]; then
    echo "❌ Missing DATABASE_URL"
    echo ""
    echo "Usage: ./scripts/seed-production.sh postgresql://..."
    echo ""
    echo "Get DATABASE_URL from Railway:"
    echo "  railway variables | grep DATABASE_URL"
    echo "  # or"
    echo "  railway variables get DATABASE_URL"
    echo ""
    exit 1
fi

echo "🌱 Seeding FitBites production database..."
echo ""

# Export current env and temporarily override DATABASE_URL
export ORIGINAL_DB="$DATABASE_URL"
export DATABASE_URL="$PROD_DB_URL"

# Run the seed script
./venv/bin/python seed.py

# Restore original DATABASE_URL
export DATABASE_URL="$ORIGINAL_DB"

echo ""
echo "✅ Production database seeded!"
echo ""
echo "Verify recipes:"
echo "  curl https://YOUR_RAILWAY_URL/api/v1/recipes"
echo ""
