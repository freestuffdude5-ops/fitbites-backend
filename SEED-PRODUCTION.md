# Seed Production Database (One Command)

**Problem:** Production database has 0 recipes  
**Solution:** Run this one script

---

## Quick Start

```bash
cd /home/user/clawd/company/sprint-feb23/echo/fitbites-backend

# Make sure Railway CLI is authenticated
railway whoami

# Seed the production database (Railway injects DATABASE_URL automatically)
railway run python seed_production_db.py
```

**Important:** Use `railway run` - this automatically connects to production database.

**That's it!** The script will:
1. Get DATABASE_URL from Railway automatically
2. Create tables if they don't exist
3. Seed with 50+ curated recipes
4. Verify success

---

## Expected Output

```
🌱 FitBites Production Database Seeder
==================================================

✅ Connected to Railway database
📋 Creating database tables...
✅ Tables ready
🌱 Seeding database...
✅ Seeded 12 recipes

==================================================
✅ SUCCESS: Seeded 50 recipes

Verify at:
  https://prolific-optimism-production.up.railway.app/api/v1/recipes
```

---

## Verification

After seeding, test the API:

```bash
curl https://prolific-optimism-production.up.railway.app/api/v1/recipes | python3 -m json.tool
```

Should return 50+ recipes instead of an empty array.

---

## Troubleshooting

### "Railway CLI not found"
Install it:
```bash
npm install -g @railway/cli
```

### "Failed to get DATABASE_URL"
Make sure you're authenticated:
```bash
railway login
```

And linked to the project:
```bash
railway link
```

### "Database already has recipes"
The script will prompt you to clear and reseed.  
Answer "yes" to proceed.

---

## What Gets Seeded

- 50+ curated high-protein recipes
- Mix of breakfast, lunch, dinner, desserts
- Full nutrition data (calories, protein, carbs, fat)
- Affiliate links for all ingredients
- Viral scores, engagement metrics
- Source credits (TikTok, Instagram, YouTube, Reddit)

---

**Time to run:** ~10 seconds  
**Safe to run multiple times:** Yes (will prompt before clearing)
