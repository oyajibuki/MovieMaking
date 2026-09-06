#!/bin/bash
# デスクトップに「AutoCutter を起動」のショートカットを作る（macOS 用）
#
# パソコンごとにフォルダの場所が変わり得るので、各マシンで一度だけ実行する。
set -u

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  LINK_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$LINK_DIR/$SOURCE"
done
APP_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

LAUNCHER="$APP_DIR/AutoCutter を起動.command"
DESKTOP="$HOME/Desktop"
SHORTCUT="$DESKTOP/AutoCutter を起動.command"

echo "==================================="
echo "  デスクトップにショートカットを作成"
echo "==================================="
echo "本体: $LAUNCHER"
echo "作成先: $SHORTCUT"
echo

if [ ! -f "$LAUNCHER" ]; then
  echo "❌ 起動用ファイルが見つかりません。"
  read -r -p "Enter キーで閉じます..."
  exit 1
fi

# Google ドライブ経由だと実行権限が落ちることがあるので付け直す
chmod +x "$LAUNCHER" 2>/dev/null || true

if [ ! -d "$DESKTOP" ]; then
  echo "❌ デスクトップフォルダが見つかりません: $DESKTOP"
  read -r -p "Enter キーで閉じます..."
  exit 1
fi

if [ -e "$SHORTCUT" ] || [ -L "$SHORTCUT" ]; then
  echo "同じ名前のショートカットが既にあります。作り直します。"
  rm -f "$SHORTCUT"
fi

ln -s "$LAUNCHER" "$SHORTCUT"

# ネット経由で来たファイルに付く隔離属性を外す（未署名スクリプトの警告対策）
xattr -d com.apple.quarantine "$LAUNCHER" 2>/dev/null || true

echo
echo "✅ 作成しました。デスクトップの「AutoCutter を起動」をダブルクリックしてください。"
echo
echo "もし「開発元が未確認」と出る場合は、"
echo "右クリック →「開く」→「開く」を一度だけ選んでください。"
echo
read -r -p "Enter キーで閉じます..."
