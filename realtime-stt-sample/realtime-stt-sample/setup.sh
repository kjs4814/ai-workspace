#!/usr/bin/env bash
# 테스터용 1회 셋업. venv 를 만들고 의존성을 설치한다.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 가 필요합니다."; exit 1; }

PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "python ${PYV}"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "python 3.10 이상이 필요합니다 (현재 ${PYV})."; exit 1; }

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -r requirements.txt
echo "의존성 설치 완료."

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo ".env 를 만들었습니다. 아래 두 값을 채우세요:"
  echo "  RAG_SUITE_BASE_URL=https://<발급받은-주소>.proxy.dxg.aifoundry.ktcloud.com"
  echo "  RAG_SUITE_TOKEN=kt_..."
  echo
  echo "그다음 ./run.sh 를 실행하고 http://127.0.0.1:8848 을 여세요."
else
  echo "이미 .env 가 있습니다. ./run.sh 로 실행하세요."
fi

echo
echo "API 호출 없이 동작만 확인하려면: .venv/bin/python test_offline.py"
