#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  start_dev.sh — start FastAPI backend + Streamlit frontend for local dev
#
#  Usage:
#    cd ai-prompt-platform
#    bash scripts/start_dev.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Copy .env if missing
if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo "[setup] Created .env from .env.example — please add your API keys."
fi

# Create storage dirs
mkdir -p storage/uploads storage/results/markdown storage/results/excel logs

# Kill any processes on our ports when the script exits
cleanup() {
    echo ""
    echo "[stop] Shutting down…"
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ── Start backend ──────────────────────────────────────────────────────────────
echo "[backend] Starting FastAPI on http://localhost:8000"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 \
    >> logs/backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend health
echo -n "[backend] Waiting for health check"
for i in $(seq 1 20); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo " OK"
        break
    fi
    echo -n "."
    sleep 1
done

# ── Start frontend ─────────────────────────────────────────────────────────────
echo "[frontend] Starting Streamlit on http://localhost:8501"
streamlit run frontend/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false \
    >> logs/frontend.log 2>&1 &
FRONTEND_PID=$!

echo ""
echo "──────────────────────────────────────────────────────────"
echo "  Backend  → http://localhost:8000/api/v1/docs"
echo "  Frontend → http://localhost:8501"
echo "  Logs     → logs/backend.log  |  logs/frontend.log"
echo "  Press Ctrl+C to stop."
echo "──────────────────────────────────────────────────────────"

# Tail both logs live
tail -f logs/backend.log logs/frontend.log
