#!/usr/bin/env bash
set -euo pipefail

# FitBites Database Backup Script
# Usage: ./scripts/backup.sh [output_dir]
# For cron: 0 */6 * * * /app/scripts/backup.sh /backups

OUTPUT_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$OUTPUT_DIR/fitbites_${TIMESTAMP}.sql.gz"

mkdir -p "$OUTPUT_DIR"

# Check if using PostgreSQL or SQLite
if [[ "${DATABASE_URL:-}" == *"postgresql"* ]]; then
    # Extract connection params from DATABASE_URL
    # Format: postgresql://user:pass@host:port/dbname
    DB_HOST=$(echo "$DATABASE_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    DB_PORT=$(echo "$DATABASE_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    DB_NAME=$(echo "$DATABASE_URL" | sed -n 's|.*/\([^?]*\).*|\1|p')
    DB_USER=$(echo "$DATABASE_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')

    echo "📦 Backing up PostgreSQL: $DB_NAME → $BACKUP_FILE"
    PGPASSWORD=$(echo "$DATABASE_URL" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p') \
        pg_dump -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" "$DB_NAME" \
        | gzip > "$BACKUP_FILE"
else
    DB_FILE="${DATABASE_URL:-fitbites.db}"
    DB_FILE="${DB_FILE#sqlite+aiosqlite:///}"
    DB_FILE="${DB_FILE#sqlite:///}"

    echo "📦 Backing up SQLite: $DB_FILE → $BACKUP_FILE"
    sqlite3 "$DB_FILE" .dump | gzip > "$BACKUP_FILE"
fi

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "✅ Backup complete: $BACKUP_FILE ($SIZE)"

# Cleanup: keep last 30 backups
ls -t "$OUTPUT_DIR"/fitbites_*.sql.gz 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null || true
echo "🧹 Retained latest 30 backups"
