#!/usr/bin/env python3
"""
Seed Production Database - One-Command Solution
===============================================

Seeds the FitBites production PostgreSQL database with initial recipes.

Usage:
    python seed_production_db.py

The script will:
1. Connect to Railway production database
2. Seed with 50+ curated recipes
3. Verify insertion
4. Print success message

Prerequisites:
- Railway CLI installed and authenticated
- You're in the fitbites-backend directory
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path so we can import from src/
sys.path.insert(0, str(Path(__file__).parent))

async def main():
    print("🌱 FitBites Production Database Seeder")
    print("=" * 50)
    print()
    
    # Use DATABASE_URL from environment (Railway injects this when using 'railway run')
    import os
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ DATABASE_URL not set")
        print("   This script must be run via: railway run python seed_production_db.py")
        print("   Railway will automatically inject the production DATABASE_URL")
        return 1
    
    if "sqlite" in database_url:
        print("⚠️  WARNING: DATABASE_URL points to SQLite, not production PostgreSQL")
        print(f"   Current: {database_url}")
        response = input("   Continue anyway? (yes/no): ").lower()
        if response != "yes":
            return 0
    
    print(f"✅ Using database: {database_url.split('@')[1] if '@' in database_url else 'local'}")
    
    # Import after setting DATABASE_URL
    from src.db.engine import engine, async_session
    from src.db.tables import Base, RecipeRow
    from sqlalchemy import select, func
    
    # Create tables
    print("📋 Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tables ready")
    
    # Check if recipes already exist
    async with async_session() as session:
        result = await session.execute(select(func.count(RecipeRow.id)))
        existing_count = result.scalar()
        
        if existing_count > 0:
            print(f"⚠️  Database already has {existing_count} recipes")
            response = input("   Clear and reseed? (yes/no): ").lower()
            if response != "yes":
                print("   Seeding cancelled")
                return 0
            
            # Clear recipes
            from sqlalchemy import delete
            await session.execute(delete(RecipeRow))
            await session.commit()
            print("   Cleared existing recipes")
    
    # Run seed.py
    print("🌱 Seeding database...")
    
    # Import and run the seed function
    import seed
    await seed.seed()
    
    # Verify
    async with async_session() as session:
        result = await session.execute(select(func.count(RecipeRow.id)))
        final_count = result.scalar()
    
    print()
    print("=" * 50)
    print(f"✅ SUCCESS: Seeded {final_count} recipes")
    print()
    print("Verify at:")
    print("  https://prolific-optimism-production.up.railway.app/api/v1/recipes")
    print()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
