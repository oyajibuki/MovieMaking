#!/usr/bin/env bash
# AutoCutter PRO のセットアップ
# openai-whisper / torch の対応状況から Python 3.10-3.12 が必要
set -euo pipefail
cd "$(dirname "$0")"

# --- Python を探す（PYTHON 環境変数で明示指定も可） ---
PY=""
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
else
  for cand in python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi

if [ -z "$PY" ]; then
  cat >&2 <<'MSG'
❌ Python 3.10-3.12 が見つかりません。

  brew install python@3.12

を実行してから、もう一度 ./setup.sh を実行してください。
（openai-whisper が依存する torch が Python 3.13 以降に未対応のため、
  システムの python3 が 3.13+ の場合はそのままでは使えません）
MSG
  echo "現在の python3: $(python3 -V 2>&1)" >&2
  exit 1
fi

echo "✅ 使用する Python: $("$PY" -V) ($(command -v "$PY"))"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "❌ ffmpeg が見つかりません。brew install ffmpeg を実行してください。" >&2
  exit 1
fi
echo "✅ ffmpeg: $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3)"

echo
echo "📦 仮想環境を作成中..."
"$PY" -m venv .venv
./.venv/bin/pip install --upgrade pip --quiet
./.venv/bin/pip install -r requirements.txt

echo
echo "🎉 セットアップ完了。起動するには:"
echo "  cd \"$(pwd)\""
echo "  ./.venv/bin/streamlit run app.py"
