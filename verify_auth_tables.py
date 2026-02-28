"""Verify authentication and user data tables exist in the database.

Run this script to check if all required tables for the auth system are present.
"""
import asyncio
import sys
from sqlalchemy import text
from src.db.engine import engine

async def verify_tables():
    """Check if all required tables exist."""
    required_tables = [
        'users',
        'saved_recipes',
        'meal_plans',
        'meal_plan_entries',
        'daily_logs',
        'meal_log_entries',
        'meal_logs',
        'user_goals',
    ]
    
    missing_tables = []
    existing_tables = []
    
    async with engine.begin() as conn:
        for table_name in required_tables:
            result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = :table_name
                    );
                """),
                {"table_name": table_name}
            )
            exists = result.scalar()
            
            if exists:
                existing_tables.append(table_name)
                print(f"✅ {table_name}")
            else:
                missing_tables.append(table_name)
                print(f"❌ {table_name} - MISSING")
    
    print(f"\n{'='*50}")
    print(f"Summary: {len(existing_tables)}/{len(required_tables)} tables exist")
    
    if missing_tables:
        print(f"\n⚠️  Missing tables: {', '.join(missing_tables)}")
        print("\nTo create missing tables, run:")
        print("python -c \"import asyncio; from src.db.engine import engine; from src.db.tables import Base; import src.db.user_tables; import src.db.meal_plan_tables; import src.db.tracking_tables; asyncio.run((lambda: engine.begin()).__call__().run_sync(Base.metadata.create_all))\"")
        return False
    else:
        print("\n✅ All required tables exist!")
        return True

async def verify_user_table_schema():
    """Verify users table has all required columns."""
    print(f"\n{'='*50}")
    print("Verifying users table schema...")
    
    required_columns = {
        'id': 'character varying',
        'email': 'character varying',
        'password_hash': 'character varying',
        'display_name': 'character varying',
        'avatar_url': 'character varying',
        'preferences': 'json',
        'created_at': 'timestamp',
        'last_active_at': 'timestamp',
    }
    
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'users';
            """)
        )
        
        columns = {row[0]: row[1] for row in result}
        
        missing_columns = []
        for col_name, expected_type in required_columns.items():
            if col_name in columns:
                print(f"✅ {col_name} ({columns[col_name]})")
            else:
                missing_columns.append(col_name)
                print(f"❌ {col_name} - MISSING")
        
        if missing_columns:
            print(f"\n⚠️  Missing columns in users table: {', '.join(missing_columns)}")
            return False
        else:
            print("\n✅ Users table schema is correct!")
            return True

async def verify_saved_recipes_table():
    """Verify saved_recipes table has foreign key constraints."""
    print(f"\n{'='*50}")
    print("Verifying saved_recipes table constraints...")
    
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT
                    tc.constraint_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.table_name = 'saved_recipes'
                AND tc.constraint_type = 'FOREIGN KEY';
            """)
        )
        
        constraints = list(result)
        
        if not constraints:
            print("❌ No foreign key constraints found")
            return False
        
        for constraint in constraints:
            print(f"✅ {constraint[1]} → {constraint[2]}.{constraint[3]}")
        
        print("\n✅ Foreign key constraints are set up correctly!")
        return True

async def test_auth_flow():
    """Test basic auth operations."""
    print(f"\n{'='*50}")
    print("Testing basic database operations...")
    
    from src.db.user_tables import UserRow
    from src.auth import hash_password
    from sqlalchemy import select, delete
    from src.db.engine import async_session
    
    test_email = "db-test@fitbites.app"
    
    async with async_session() as session:
        # Clean up any existing test user
        await session.execute(
            delete(UserRow).where(UserRow.email == test_email)
        )
        await session.commit()
        
        # Create test user
        test_user = UserRow(
            email=test_email,
            password_hash=hash_password("testpassword123"),
            display_name="DB Test User"
        )
        session.add(test_user)
        await session.commit()
        print("✅ Created test user")
        
        # Retrieve test user
        result = await session.execute(
            select(UserRow).where(UserRow.email == test_email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            print(f"✅ Retrieved test user: {user.email}")
        else:
            print("❌ Failed to retrieve test user")
            return False
        
        # Clean up
        await session.execute(
            delete(UserRow).where(UserRow.email == test_email)
        )
        await session.commit()
        print("✅ Cleaned up test user")
    
    return True

async def main():
    """Run all verification checks."""
    print("FitBites Auth System - Database Verification")
    print("=" * 50)
    
    try:
        # Check table existence
        tables_ok = await verify_tables()
        
        if not tables_ok:
            print("\n❌ Verification failed: Missing tables")
            return False
        
        # Check users table schema
        schema_ok = await verify_user_table_schema()
        
        if not schema_ok:
            print("\n❌ Verification failed: Incorrect schema")
            return False
        
        # Check foreign key constraints
        constraints_ok = await verify_saved_recipes_table()
        
        if not constraints_ok:
            print("\n❌ Verification failed: Missing constraints")
            return False
        
        # Test basic operations
        operations_ok = await test_auth_flow()
        
        if not operations_ok:
            print("\n❌ Verification failed: Database operations failed")
            return False
        
        print("\n" + "=" * 50)
        print("✅ ALL CHECKS PASSED!")
        print("=" * 50)
        print("\nYour database is ready for authentication!")
        return True
        
    except Exception as e:
        print(f"\n❌ Verification failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await engine.dispose()

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
