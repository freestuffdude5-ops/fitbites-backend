# Quick Deploy Guide - FitBites Backend

## 🚀 Deploy in 3 Steps

### Step 1: Push to GitHub

```bash
cd /home/user/clawd/company/sprint-feb23/echo/fitbites-backend

# Create new GitHub repo at: https://github.com/new
# Name it: fitbites-backend

# Add remote and push
git remote add origin https://github.com/YOUR_USERNAME/fitbites-backend.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy on Railway

1. Go to [railway.app/dashboard](https://railway.app/dashboard)
2. Click **"New Project"**
3. Click **"Deploy from GitHub repo"**
4. Select **fitbites-backend**
5. Railway auto-detects `Dockerfile` and `railway.toml`
6. Click **"Deploy"**

### Step 3: Configure Environment Variables

In Railway dashboard, go to **Settings → Variables** and add:

**Required:**
```
JWT_SECRET=your_random_64_char_secret_here
CORS_ORIGINS=https://fitbites.app
API_BASE_URL=https://your-railway-url.up.railway.app
```

**Optional (for scrapers):**
```
YOUTUBE_API_KEY=your_key
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
```

Railway will auto-provide `DATABASE_URL` (PostgreSQL).

---

## ✅ Verify Deployment

After deployment completes:

```bash
# Get your Railway URL from dashboard, then:
curl https://your-app.up.railway.app/health

# Should return: {"status":"ok","db":"connected","version":"0.2.0"}
```

---

## 🎉 Done!

Your API is now live. Access:
- **Health check:** https://your-app.up.railway.app/health
- **API docs:** https://your-app.up.railway.app/docs
- **Recipes:** https://your-app.up.railway.app/api/v1/recipes

To populate recipes, run the scraper:
```bash
curl -X POST https://your-app.up.railway.app/api/v1/scrape/reddit
```

---

**Need help?** Contact NOVA via `sessions_send`
