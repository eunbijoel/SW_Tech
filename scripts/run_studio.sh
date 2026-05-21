#!/usr/bin/env bash
# SW_Tech — AI Excel Agent Studio (페르소나·라이트 테마)
# excel-platform 과 혼동 방지: 반드시 이 스크립트로 실행하세요.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=============================================="
echo "  AI Excel Agent Studio  (SW_Tech/app.py)"
echo "  사이드바 확인: 📍 SW_Tech · app.py · 라이트 테마"
echo "  잘못된 화면: Excel AI Platform → 다른 프로젝트"
echo "=============================================="

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# 8501은 Windows/excel-platform 과 Cursor 포트 충돌이 잦음 → 8502 고정
PORT="${PORT:-8502}"
echo "→ 서버: http://localhost:${PORT}"
echo "→ Cursor 사용 시: 포트 8502 포워딩 후 브라우저에서 위 주소로 접속"
echo "   (Windows 로컬 8501에 excel-platform 이 떠 있으면 8501은 잘못된 앱입니다)"
exec streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0
