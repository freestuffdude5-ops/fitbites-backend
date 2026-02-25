#!/bin/bash
# One-click deployment to Railway
# Prerequisites: Railway CLI installed and authenticated (`railway login`)
# Usage: ./scripts/deploy-railway.sh

set -e

echo "🚀 FitBites Backend - Railway Deployment"
echo "========================================"
echo ""

# Check if Railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found!"
    echo ""
    echo "Install it:"
    echo "  npm install -g @railway/cli"
    echo "  # or"
    echo "  brew install railway"
    echo ""
    exit 1
fi

# Check if logged in
if ! railway whoami &> /dev/null; then
    echo "❌ Not logged in to Railway!"
    echo ""
    echo "Run: railway login"
    echo ""
    exit 1
fi

echo "✅ Railway CLI found and authenticated"
echo ""

# Check if project is linked
if ! railway status &> /dev/null; then
    echo "❓ No Railway project linked to this directory."
    echo ""
    read -p "Create a new Railway project? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        railway init
    else
        echo "❌ Deployment cancelled"
        exit 1
    fi
fi

echo "📦 Railway project: $(railway status | grep 'Project:' | awk '{print $2}')"
echo ""

# Check if secrets exist
if [ ! -f ".env.production" ]; then
    echo "⚠️  No .env.production file found!"
    echo ""
    read -p "Generate production secrets now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ./scripts/generate-secrets.sh > .env.production
        echo "✅ Secrets generated: .env.production"
        echo "⚠️  Upload these to Railway variables manually or use:"
        echo "   railway variables --set-from-file .env.production"
        echo ""
    fi
fi

# Run tests before deploying
echo "🧪 Running tests..."
if ./venv/bin/python -m pytest tests/ -q --tb=short; then
    echo "✅ All tests passed"
else
    echo "❌ Tests failed! Fix them before deploying."
    exit 1
fi
echo ""

# Build check
echo "🔨 Checking if Dockerfile builds..."
if docker build -t fitbites-backend-test . > /dev/null 2>&1; then
    echo "✅ Docker build successful"
else
    echo "❌ Docker build failed! Check Dockerfile."
    exit 1
fi
echo ""

# Deploy
echo "🚀 Deploying to Railway..."
echo ""
read -p "Proceed with deployment? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Deployment cancelled"
    exit 1
fi

railway up

echo ""
echo "✅ Deployment triggered!"
echo ""
echo "🔍 Monitor deployment:"
echo "   railway logs"
echo ""
echo "🌐 Get deployment URL:"
echo "   railway domain"
echo ""
echo "⚙️  Set environment variables (if not done yet):"
echo "   railway variables --set-from-file .env.production"
echo ""
echo "📊 Check service status:"
echo "   railway status"
echo ""
