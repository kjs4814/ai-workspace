#!/usr/bin/env bash
# 개발 서버 실행. .env 를 읽어 환경변수로 넣는다.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "의존성이 설치되지 않았습니다. 먼저 아래를 실행하세요:"
  echo
  echo "  ./setup.sh"
  echo
  exit 1
fi

# 폴더를 통째로 복사해 온 경우 venv 안의 shebang 이 원래 경로를 가리켜 깨진다.
# .venv 는 배포에 포함하면 안 되지만, 실수로 딸려온 경우를 여기서 잡아준다.
if ! .venv/bin/python -c '' 2>/dev/null; then
  echo ".venv 가 이 경로에서 동작하지 않습니다 (다른 PC 에서 만들어진 venv 로 보입니다)."
  echo "아래로 다시 만드세요:"
  echo
  echo "  rm -rf .venv && ./setup.sh"
  echo
  exit 1
fi

[ -f .env ] || { echo ".env 가 없습니다. cp .env.example .env 후 값을 채우세요."; exit 1; }
set -a; . ./.env; set +a

if [ -z "${RAG_SUITE_TOKEN:-}" ] || [ "${RAG_SUITE_TOKEN}" = "kt_YOUR_TOKEN_HERE" ]; then
  echo ".env 의 RAG_SUITE_TOKEN 이 아직 예시값입니다. 발급받은 토큰으로 바꾸세요."
  exit 1
fi

PORT="${PORT:-8848}"
echo "http://127.0.0.1:${PORT} 를 브라우저에서 여세요."
exec .venv/bin/uvicorn server.app:app --host 127.0.0.1 --port "$PORT" "$@"
