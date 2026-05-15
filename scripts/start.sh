#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  start.sh — production start via Docker Compose
#
#  Usage:
#    cd ai-prompt-platform
#    bash scripts/start.sh          # standard
#    bash scripts/start.sh prod     # production overrides (GPU, multi-replica)
#    bash scripts/start.sh stop     # stop all containers
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"

case "$MODE" in
  stop)
    echo "[docker] Stopping containers…"
    docker compose -f docker/docker-compose.yml down
    echo "[docker] Done."
    ;;
  prod)
    echo "[docker] Starting in PRODUCTION mode…"
    docker compose \
        -f docker/docker-compose.yml \
        -f docker/docker-compose.prod.yml \
        up --build -d
    echo ""
    echo "  Backend  → http://localhost:8000/api/v1/docs"
    echo "  Frontend → http://localhost:8501"
    ;;
  *)
    echo "[docker] Starting in development mode…"
    docker compose -f docker/docker-compose.yml up --build -d
    echo ""
    echo "  Backend  → http://localhost:8000/api/v1/docs"
    echo "  Frontend → http://localhost:8501"
    echo "  Logs:  docker compose -f docker/docker-compose.yml logs -f"
    ;;
esac
