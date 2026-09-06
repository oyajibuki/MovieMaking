#!/usr/bin/env bash
# ローカルで AutoCutter PRO を起動する
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ./.venv/bin/python ]; then
  echo "先に ./setup.sh を実行してください。" >&2
  exit 1
fi

PORT="${PORT:-7860}"
echo "http://localhost:$PORT で起動します（終了は Ctrl+C）"

# 起動を待ってからブラウザを開く
( until curl -sf -o /dev/null "http://localhost:$PORT" 2>/dev/null; do sleep 1; done
  command -v open >/dev/null && open "http://localhost:$PORT" ) &

PORT="$PORT" exec ./.venv/bin/python app.py
