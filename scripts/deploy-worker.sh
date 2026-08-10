#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env.worker ]; then
  echo ".env.worker is missing; create it from .env.worker.example" >&2
  exit 1
fi

if ! grep -Eq '^DATABASE_URL=postgres(ql)?://.+' .env.worker; then
  echo "DATABASE_URL is missing from .env.worker" >&2
  exit 1
fi

docker compose -f docker-compose.worker.yml config --quiet
docker compose -f docker-compose.worker.yml up -d --build --remove-orphans
docker compose -f docker-compose.worker.yml ps
