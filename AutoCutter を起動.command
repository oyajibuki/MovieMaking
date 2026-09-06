#!/bin/bash
# ダブルクリックで AutoCutter PRO を起動する（macOS 用）
#
# .command 拡張子にすると Finder のダブルクリックで Terminal が開いて実行される。
# デスクトップに置いたショートカット（シンボリックリンク）からでも動くように、
# リンクをたどって本体の場所を求めている。

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  LINK_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$LINK_DIR/$SOURCE"
done
APP_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$APP_DIR" || exit 1

PORT="${PORT:-7860}"

echo "==================================="
echo "  ✂️  AutoCutter PRO"
echo "==================================="
echo "フォルダ: $APP_DIR"
echo

# --- 既に起動していれば、そのまま開くだけ ---
if curl -sf -o /dev/null "http://localhost:$PORT" 2>/dev/null; then
  echo "すでに起動しています。ブラウザを開きます。"
  open "http://localhost:$PORT"
  echo
  echo "このウィンドウは閉じて構いません。"
  exit 0
fi

# --- 初回セットアップの確認 ---
if [ ! -x "./.venv/bin/python" ]; then
  echo "⚠️  初回セットアップがまだのようです。"
  echo
  read -r -p "いまセットアップしますか？（数分かかります）[y/N] " answer
  case "$answer" in
    [yY]*)
      if ! ./setup.sh; then
        echo
        echo "❌ セットアップに失敗しました。上のメッセージを確認してください。"
        read -r -p "Enter キーで閉じます..."
        exit 1
      fi
      ;;
    *)
      echo "中止しました。ターミナルで ./setup.sh を実行してください。"
      read -r -p "Enter キーで閉じます..."
      exit 1
      ;;
  esac
fi

echo "起動しています... 少し待つとブラウザが自動で開きます。"
echo "終了するには、このウィンドウで Control + C を押してください。"
echo

# 起動を待ってからブラウザを開く
(
  for _ in $(seq 1 120); do
    if curl -sf -o /dev/null "http://localhost:$PORT" 2>/dev/null; then
      open "http://localhost:$PORT"
      exit 0
    fi
    sleep 1
  done
) &

PORT="$PORT" ./.venv/bin/python app.py
STATUS=$?

echo
if [ $STATUS -ne 0 ]; then
  echo "❌ 終了コード $STATUS で終了しました。上のメッセージを確認してください。"
  read -r -p "Enter キーで閉じます..."
fi
