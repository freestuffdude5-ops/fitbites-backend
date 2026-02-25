# FitBites Backend - Deployment Guide

## Production Infrastructure

**Current Status:** ✅ Deployed on Railway  
**Live URL:** https://prolific-optimism-production.up.railway.app  
**Health Check:** https://prolific-optimism-production.up.railway.app/health

---

## Quick Deploy (Manual)

```bash
# From backend directory
railway up
```

The CI pipeline will automatically deploy on push to `master` or `main` once secrets are configured.

---

## GitHub Secrets (for CI/CD)

To enable automatic deployment, add these secrets to GitHub repo settings:

1. **RAILWAY_TOKEN**
   - Get from: `railway login` then `railway whoami --json | jq -r .token`
   - Purpose: Authenticate GitHub Actions to Railway

2. **RAILWAY_PROJECT_ID**
   - Get from: Railway dashboard URL or `railway status`
   - Example: `5d0d9ead-571b-4a82-95af-01505a8cce40`

3. **RAILWAY_URL**
   - Value: `https://prolific-optimism-production.up.railway.app`
   - Purpose: Health check after deployment

### Adding Secrets to GitHub

```bash
# Via GitHub CLI
gh secret set RAILWAY_TOKEN --body "YOUR_TOKEN_HERE"
gh secret set RAILWAY_PROJECT_ID --body "5d0d9ead-571b-4a82-95af-01505a8cce40"
gh secret set RAILWAY_URL --body "https://prolific-optimism-production.up.railway.app"
```

Or: GitHub repo → Settings → Secrets and variables → Actions → New repository secret

---

## Railway Environment Variables

Current configuration (managed via Railway dashboard or CLI):

```bash
# View current vars
railway variables

# Set a variable
railway variables set SENTRY_DSN=https://...
```

**Required for production:**
- `JWT_SECRET` - Secure random string (64+ chars)
- `DATABASE_URL` - Auto-set by Railway PostgreSQL
- `CORS_ORIGINS` - Comma-separated allowed origins
- `API_BASE_URL` - Base URL for affiliate links

**Optional (for scraping):**
- `YOUTUBE_API_KEY`
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`
- `ANTHROPIC_API_KEY`

**Optional (for monitoring):**
- `SENTRY_DSN` - Sentry error tracking
- `SENTRY_ENVIRONMENT` - `production` or `staging`
- `LOG_FORMAT` - `json` for production, `text` for dev

---

## Continuous Deployment Workflow

1. Developer pushes to `master` or `main`
2. GitHub Actions runs:
   - ✅ Tests (271 tests)
   - ✅ Docker build + health check
   - ✅ Security audit (pip-audit)
   - 🚀 Deploy to Railway (if tests pass)
   - ✅ Verify deployment health check
3. Railway builds and deploys new image
4. Health check confirms deployment success

**Time:** ~3-5 minutes from push to live

---

## Monitoring & Observability

### Health Checks
- **Endpoint:** `/health` - Returns `{status, db, version}`
- **Readiness:** `/ready` - Returns 503 if DB unavailable

### Metrics (Prometheus)
- **Endpoint:** `/metrics`
- **Tracks:** Request count, duration, active requests, uptime
- **Integration:** Configure Prometheus to scrape `/metrics`

### Error Tracking (Sentry)
- **Setup:** Set `SENTRY_DSN` in Railway
- **Dashboard:** Sentry project dashboard
- **Sampling:** 10% traces, 10% profiles (configurable)

### Logs
- **Format:** JSON (structured) in production
- **Access:** `railway logs` or Railway dashboard
- **Aggregation:** Export to Datadog/CloudWatch if needed

---

## Database Management

### Migrations

```bash
# Generate migration from model changes
make migrate-gen msg="Add new column"

# Apply migrations
make migrate

# View history
make migrate-history
```

### Backups

```bash
# Manual backup (supports PostgreSQL and SQLite)
./scripts/backup.sh

# Backups stored in: backups/fitbites_YYYYMMDD_HHMMSS.sql
# Auto-cleanup: keeps last 30 backups
```

**Railway:** Automatic backups available on Pro plan

---

## Performance & Scaling

**Current configuration:**
- **Workers:** 1 (Railway default)
- **Connection pool:** 10 connections, 20 max overflow
- **Rate limits:** 120 req/min general, 10 req/min auth
- **Cache:** In-memory (30s recipe lists, 60s trending)

**Scaling considerations:**
- Add workers: Update `railway.toml` start command
- PostgreSQL: Monitor connection pool usage
- Redis: For distributed caching (future)
- CDN: For static assets when frontend deploys

---

## Troubleshooting

### Build Fails

```bash
# Check logs
railway logs

# Rebuild locally
docker build -t fitbites-test .
docker run -p 8000:8000 fitbites-test

# Verify dependencies
pip install -e ".[dev]"
python -m pytest tests/ -v
```

### Database Connection Issues

```bash
# Check DATABASE_URL is set
railway variables | grep DATABASE_URL

# Test local DB connection
python -c "from src.db.engine import engine; print('✅ DB connected')"
```

### Health Check Fails

```bash
# Check app is running
curl https://prolific-optimism-production.up.railway.app/health

# View recent logs
railway logs -n 50

# Check Railway dashboard for service status
```

---

## Security Checklist

- ✅ JWT_SECRET is random and secure (not default)
- ✅ CORS_ORIGINS is restricted (not wildcard `*`)
- ✅ Rate limiting enabled (brute-force protection)
- ✅ Security headers (HSTS, X-Frame-Options, etc.)
- ✅ Error tracking (Sentry) with PII scrubbing
- ✅ Database connections use SSL (Railway)
- ✅ Dependencies audited (pip-audit in CI)

---

## Support

**Issues:** Check Railway logs first, then Sentry errors  
**Contact:** BYTE (DevOps) or ECHO (Backend)  
**Docs:** `/docs` endpoint (FastAPI auto-docs)
