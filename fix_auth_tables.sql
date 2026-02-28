-- Drop auth tables to recreate with correct timezone-aware columns
DROP TABLE IF EXISTS grocery_lists CASCADE;
DROP TABLE IF EXISTS saved_recipes CASCADE;
DROP TABLE IF EXISTS user_goals CASCADE;
DROP TABLE IF EXISTS meal_log_entries CASCADE;
DROP TABLE IF EXISTS daily_logs CASCADE;
DROP TABLE IF EXISTS meal_plan_entries CASCADE;
DROP TABLE IF EXISTS meal_plans CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Tables will be recreated automatically on next backend startup via create_all()
