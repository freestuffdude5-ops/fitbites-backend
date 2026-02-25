#!/bin/bash
# FitBites Backend - Railway Deployment Script
# Run this after: railway login

set -e  # Exit on error

echo "🚀 FitBites Backend Railway Deployment"
echo "========================================"

# Check Railway CLI
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found. Install: npm install -g @railway/cli"
    exit 1
fi

# Check auth
if ! railway whoami &> /dev/null; then
    echo "❌ Not logged in to Railway. Run: railway login"
    exit 1
fi

echo "✅ Railway CLI authenticated"

# Initialize project (if not exists)
if [ ! -f "railway.json" ]; then
    echo "📦 Initializing Railway project..."
    railway init --name fitbites-api
else
    echo "✅ Railway project already initialized"
fi

# Add PostgreSQL (if not exists)
echo "🗄️  Checking for PostgreSQL database..."
if ! railway variables | grep -q "DATABASE_URL"; then
    echo "Adding PostgreSQL database..."
    railway add --database postgres
    echo "✅ PostgreSQL added"
else
    echo "✅ PostgreSQL already configured"
fi

# Set environment variables
echo "🔧 Setting environment variables..."

# Generate JWT secret if not set
if ! railway variables | grep -q "JWT_SECRET"; then
    JWT_SECRET=$(openssl rand -hex 32)
    railway variables set JWT_SECRET="$JWT_SECRET"
    echo "✅ JWT_SECRET generated"
fi

railway variables set API_BASE_URL="https://fitbites-api.up.railway.app" \
    CORS_ORIGINS="https://fitbites-web.up.railway.app,https://fitbites.io" \
    LOG_FORMAT="json" \
    LOG_LEVEL="INFO"

echo "✅ Environment variables configured"

# Deploy
echo "🚢 Deploying to Railway..."
railway up --detach

echo ""
echo "✅ Deployment initiated!"
echo "📊 View logs: railway logs"
echo "🌐 Service URL: https://fitbites-api.up.railway.app"
echo "🏥 Health check: https://fitbites-api.up.railway.app/health"
echo ""
echo "⏳ Waiting for deployment to complete..."
sleep 30

# Test health endpoint
echo "🔍 Testing health endpoint..."
if curl -f -s https://fitbites-api.up.railway.app/health > /dev/null; then
    echo "✅ Backend API is LIVE!"
    curl -s https://fitbites-api.up.railway.app/health | python3 -m json.tool
else
    echo "⚠️  Health check failed. Check logs: railway logs"
    exit 1
fi

echo ""
echo "🎉 FitBites Backend successfully deployed!"
echo "📖 API Docs: https://fitbites-api.up.railway.app/docs"
