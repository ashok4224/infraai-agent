#!/bin/bash
set -e

echo "=== InfraAI Backend Startup ==="

# Run Alembic migrations (creates/updates tables automatically)
echo "Running database migrations..."
cd /app
if ! alembic upgrade head 2>&1; then
  echo "⚠️  Migration failed. If you see 'permission denied for table alembic_version',"
  echo "   the table was likely created by a different DB user."
  echo "   Fix: connect as superuser and run:"
  echo "     GRANT ALL ON ALL TABLES IN SCHEMA public TO <your_db_user>;"
  echo "     GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO <your_db_user>;"
  echo "   Or delete the persistent volume and redeploy for a fresh start."
  exit 1
fi
echo "✅ Database migrations complete"

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-keep-alive 120
