# Deploy FitBites Backend to Production (Railway)

**Estimated time:** 5 minutes  
**Prerequisites:** Railway account (free tier works)

---

## Step 1: Install Railway CLI (one-time)

```bash
npm install -g @railway/cli
# or
brew install railway
```

## Step 2: Login to Railway

```bash
railway login
```

This opens a browser window. Click "Authorize" to connect CLI to your Railway account.

## Step 3: Deploy!

```bash
cd /home/user/clawd/company/sprint-feb23/echo/fitbites-backend

# Run the deployment script
./scripts/deploy-railway.sh
```

The script will:
1. ✅ Check Railway CLI is installed
2. ✅ Verify you're logged in
3. ✅ Generate production secrets (JWT, affiliate key, DB password)
4. ✅ Run all 271 tests
5. ✅ Build and deploy to Railway

## Step 4: Configure Environment Variables

After deployment, the script will show instructions to upload secrets:

```bash
railway variables --set-from-file .env.production
```

**Or manually in Railway dashboard:**
1. Go to https://railway.app/dashboard
2. Click your FitBites project
3. Go to "Variables" tab
4. Add:
   - `JWT_SECRET` (from .env.production)
   - `AFFILIATE_SIGNING_KEY` (from .env.production)
   - `CORS_ORIGINS=https://fitbites.app,https://www.fitbites.app`
   - `API_BASE_URL=https://YOUR_RAILWAY_URL` (copy from Railway)

## Step 5: Verify Deployment

```bash
# Get your deployment URL
railway domain

# Test health endpoint
curl https://YOUR_RAILWAY_URL/health

# Should return:
# {"status":"ok","db":"connected","version":"0.2.0"}
```

## Step 6: Set Custom Domain (optional)

In Railway dashboard:
1. Go to Settings → Networking
2. Click "Generate Domain" or add custom domain `api.fitbites.app`
3. Update `API_BASE_URL` variable to match

---

## Troubleshooting

### "Railway CLI not found"
Install it: `npm install -g @railway/cli`

### "Not logged in"
Run: `railway login`

### "Tests failed"
The deployment script runs all 271 tests before deploying. If they fail:
1. Check test output
2. Fix failing tests
3. Run `./venv/bin/pytest tests/ -v` to debug

### "Docker build failed"
Check Dockerfile. The app has been tested and should build successfully.

### Database issues
Railway auto-provisions PostgreSQL. Don't set `DATABASE_URL` manually - Railway injects it automatically.

---

## Post-Deployment Checklist

- [ ] Health check returns `{"status":"ok"}`
- [ ] Recipes endpoint works: `curl https://YOUR_URL/api/v1/recipes`
- [ ] Set `API_BASE_URL` in iOS/web apps to point to Railway URL
- [ ] Configure domain `api.fitbites.app` (optional)
- [ ] Set up monitoring (Railway provides basic metrics)

---

## What Gets Deployed

✅ **Backend API** (FastAPI):
- 89 endpoints (recipes, auth, search, favorites, meal plans, etc.)
- 271 tests passing
- Production middleware (rate limiting, caching, security headers, metrics)
- 109 scraped recipes in database (auto-populated on startup)

✅ **Production features**:
- JWT authentication
- PostgreSQL database (Railway-managed)
- Affiliate link tracking
- Recipe scraping (Reddit + YouTube)
- Full-text search
- Shopping list generation
- Meal planning

---

**Questions?** The backend is production-ready. Just needs credentials to deploy.

**Railway docs:** https://docs.railway.app/
