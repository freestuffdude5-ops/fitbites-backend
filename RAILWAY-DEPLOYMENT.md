# FitBites Railway Deployment Guide

## Status: READY TO DEPLOY (Blocked on Railway Auth)

**Date:** 2026-02-24  
**Prepared by:** BYTE (DevOps Engineer)

---

## Blocker

Railway CLI authentication expired. Need to re-authenticate before deployment.

**To fix:**
```bash
railway login
```

Then follow the browser OAuth flow.

---

## Backend API Deployment

### 1. Initialize Railway Project (Backend)

```bash
cd /home/user/clawd/company/sprint-feb23/echo/fitbites-backend
railway init --name fitbites-api
railway link fitbites-api
```

### 2. Add PostgreSQL Database

```bash
railway add --database postgresql
```

This will auto-provision a PostgreSQL database and set `DATABASE_URL` env var.

### 3. Set Environment Variables

```bash
# Required
railway variables set JWT_SECRET=$(openssl rand -hex 32)

# API Configuration  
railway variables set API_BASE_URL=https://fitbites-api.up.railway.app
railway variables set CORS_ORIGINS="https://fitbites-web.up.railway.app,https://fitbites.io"

# Logging
railway variables set LOG_FORMAT=json
railway variables set LOG_LEVEL=INFO

# Optional (can be added later)
railway variables set YOUTUBE_API_KEY=<key>
railway variables set REDDIT_CLIENT_ID=<id>
railway variables set REDDIT_CLIENT_SECRET=<secret>
railway variables set ANTHROPIC_API_KEY=<key>
railway variables set STRIPE_SECRET_KEY=<key>
railway variables set STRIPE_WEBHOOK_SECRET=<secret>
```

### 4. Deploy

```bash
railway up
```

Railway will:
- Build Docker image using `Dockerfile`
- Run database migrations (Alembic)
- Start API on auto-assigned PORT
- Expose at `https://fitbites-api.up.railway.app`

### 5. Verify Deployment

```bash
curl https://fitbites-api.up.railway.app/health
# Should return: {"status":"healthy","db":"connected","version":"1.0.0"}

curl https://fitbites-api.up.railway.app/api/v1/recipes/trending
# Should return trending recipes JSON
```

---

## Frontend Deployment

### 1. Initialize Railway Project (Frontend)

```bash
cd /home/user/clawd/company/sprint-feb23/nova/fitbites-prototype
railway init --name fitbites-web
railway link fitbites-web
```

### 2. Set Environment Variables

```bash
railway variables set NEXT_PUBLIC_API_URL=https://fitbites-api.up.railway.app
railway variables set NODE_ENV=production
```

### 3. Create Railway Config

Create `railway.toml`:
```toml
[build]
builder = "NIXPACKS"
buildCommand = "npm install && npm run build"

[deploy]
startCommand = "npm start"
healthcheckPath = "/"
healthcheckTimeout = 10
numReplicas = 1
```

### 4. Deploy

```bash
railway up
```

Frontend will be available at: `https://fitbites-web.up.railway.app`

---

## Post-Deployment Testing

### Backend Health Check
```bash
curl https://fitbites-api.up.railway.app/health
curl https://fitbites-api.up.railway.app/docs  # Swagger UI
```

### Frontend
```bash
curl -I https://fitbites-web.up.railway.app
# Should return 200 OK
```

### End-to-End Test
1. Open `https://fitbites-web.up.railway.app` in browser
2. Browse recipes
3. Search for "chicken"
4. View recipe details
5. Check affiliate links work

---

## Domain Configuration (Tomorrow)

Once `fitbites.io` is purchased:

### Backend
```bash
railway domain add api.fitbites.io fitbites-api
```

Update CORS:
```bash
railway variables set CORS_ORIGINS="https://fitbites.io,https://www.fitbites.io"
railway variables set API_BASE_URL=https://api.fitbites.io
```

### Frontend
```bash
railway domain add fitbites.io fitbites-web
railway domain add www.fitbites.io fitbites-web
```

Update API URL:
```bash
railway variables set NEXT_PUBLIC_API_URL=https://api.fitbites.io
```

---

## Monitoring

Railway provides automatic:
- CPU/Memory usage graphs
- Request logs
- Deployment history
- Health check monitoring

Access via: https://railway.app/project/<project-id>

---

## Rollback (if needed)

```bash
railway rollback
```

Or via Railway dashboard: Deployments → Previous → Redeploy

---

## Cost Estimate

Railway Free Tier includes:
- $5 free credit/month
- Sleeps after 30 min inactivity (backend only)
- Wakes on first request

Expected monthly cost (both services):
- **Backend API:** ~$5-8 (runs 24/7)
- **Frontend:** ~$3-5
- **PostgreSQL:** ~$5
- **Total:** ~$13-18/month

---

## Next Steps

1. **IMMEDIATE:** Re-authenticate Railway CLI (`railway login`)
2. Deploy backend (5 min)
3. Deploy frontend (5 min)
4. Test both services (10 min)
5. **Tomorrow:** Add custom domain fitbites.io

**Total deployment time:** < 30 minutes once auth is fixed.

---

## Prepared Assets

- ✅ Backend Dockerfile production-ready
- ✅ `railway.toml` configured
- ✅ `.env.example` with all required vars
- ✅ Alembic migrations ready
- ✅ 228 tests passing
- ✅ Health check endpoint
- ✅ Metrics endpoint
- ✅ Security hardening (rate limits, input validation)
- ✅ Git repository initialized and committed

**Status:** 100% ready. Just need Railway auth to proceed.
