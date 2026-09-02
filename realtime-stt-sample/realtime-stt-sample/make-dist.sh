#!/usr/bin/env bash
# 남에게 건넬 zip 을 만든다.
#
# 폴더를 그냥 압축하면 안 되는 이유가 두 가지 있다.
#   .env    내 RAG Suite 토큰이 그대로 들어간다
#   .venv   shebang 에 내 홈 경로가 박혀 있어 남의 PC 에서 깨진다 (77MB 덤)
# 이 스크립트는 둘 다 빼고 묶는다.
set -euo pipefail
cd "$(dirname "$0")"

OUT="${1:-realtime-stt-sample.zip}"
rm -f "$OUT"

zip -r -q "$OUT" . \
  -x '.env' \
  -x '.venv/*' \
  -x '*/__pycache__/*' -x '__pycache__/*' -x '*.pyc' \
  -x 'probe_results.json' -x 'quality_results.json' -x 'threshold_results.json' \
  -x '.git/*' -x '.DS_Store' -x '*/.DS_Store' \
  -x "$OUT"

echo "생성: $OUT ($(du -h "$OUT" | cut -f1))"
echo
echo "포함되지 않은 것: .env(토큰), .venv(가상환경)"
echo "받는 사람은 압축을 풀고 ./setup.sh → .env 작성 → ./run.sh 순으로 실행하면 됩니다."
echo
echo "토큰 포함 여부 확인:"
if unzip -p "$OUT" '.env' >/dev/null 2>&1; then
  echo "  경고: .env 가 포함되어 있습니다."
  exit 1
fi
echo "  .env 없음 — 안전"
