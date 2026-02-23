#!/bin/sh
set -e

# Seed DB if it doesn't exist
if [ ! -f /app/data/ccchallenge.db ]; then
    echo "Seeding database..."
    python -m backend.services.seed
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
