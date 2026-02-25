.PHONY: serve test scrape seed clean lint migrate deploy docker-up docker-down

# ── Development ──────────────────────────────────

# Start API server with hot reload
serve:
	python3 -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Run all tests
test:
	python3 -m pytest tests/ -q --tb=short

# Run tests with coverage
test-cov:
	python3 -m pytest tests/ -q --tb=short --cov=src --cov-report=term-missing

# Run tests for a specific module
test-%:
	python3 -m pytest tests/test_$*.py -v

# Seed database with sample data
seed:
	python3 seed.py

# Scrape Reddit and store recipes in DB
scrape:
	python3 scripts/scrape_and_store.py

# Clean database
clean:
	rm -f fitbites.db

# ── Database ─────────────────────────────────────

# Generate new migration from model changes
migrate-gen:
	alembic revision --autogenerate -m "$(msg)"

# Apply all pending migrations
migrate:
	alembic upgrade head

# Show migration history
migrate-history:
	alembic history

# ── Docker / Production ──────────────────────────

# Build and start production stack
docker-up:
	docker compose -f docker-compose.prod.yml up -d --build

# Stop production stack
docker-down:
	docker compose -f docker-compose.prod.yml down

# View production logs
docker-logs:
	docker compose -f docker-compose.prod.yml logs -f api

# Deploy to platform (docker|railway|render)
deploy:
	./scripts/deploy.sh $(platform)

# ── Observability ────────────────────────────────

# Check API health
health:
	@curl -sf http://localhost:8000/health | python3 -m json.tool

# Show metrics
metrics:
	@curl -sf http://localhost:8000/metrics

# Show trending recipes
trending:
	@curl -sf http://localhost:8000/api/v1/trending?limit=5 | python3 -m json.tool
