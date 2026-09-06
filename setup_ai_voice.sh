#!/usr/bin/env bash
# AI 声質変換（別人の声への置き換え）を使えるようにする
#
# seed-vc を vendor/ に取得し、専用の仮想環境 .venv-vc を作る。
# 本体（.venv）とは依存が非互換（numpy 1.26 / gradio 5 など）なので分離する。
# seed-vc は GPL-3.0 のため、本体には取り込まず別プロセスとして呼び出す。
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "❌ Python 3.10-3.12 が必要です（brew install python@3.12）" >&2
  exit 1
fi

echo "📥 seed-vc を取得中..."
if [ -d vendor/seed-vc/.git ]; then
  # 当てた修正は毎回入れ直すので、取得前に元に戻しておく
  git -C vendor/seed-vc checkout -- . 2>/dev/null || true
  git -C vendor/seed-vc pull --ff-only
else
  mkdir -p vendor
  git clone --depth 1 https://github.com/Plachtaa/seed-vc.git vendor/seed-vc
fi

echo "📦 専用の仮想環境を作成中...（数分かかります）"
"$PY" -m venv .venv-vc
./.venv-vc/bin/pip install --upgrade pip --quiet

# torch は安定版を使う（Apple Silicon では MPS が効く）
./.venv-vc/bin/pip install torch torchaudio torchcodec

# seed-vc の推論に必要な依存。GUI / 評価用のパッケージは入れない
./.venv-vc/bin/pip install \
  "numpy==1.26.4" "scipy==1.13.1" "librosa==0.10.2" \
  "huggingface-hub>=0.28.1" "munch==4.0.0" "einops==0.8.0" \
  "descript-audio-codec==1.0.0" "transformers==4.46.3" \
  "soundfile==0.12.1" pyyaml "hydra-core==1.3.2" resemblyzer accelerate

# Apple Silicon（MPS）で抑揚保持が動くように seed-vc を修正する
./.venv/bin/python -c "from autocutter import ai_voice; print('MPS 対応の修正:', '適用' if ai_voice.ensure_mps_patch() else '不要')" 2>/dev/null || true

echo
echo "🎉 完了しました。"
echo "モデルは初回の変換時に自動でダウンロードされます（1GB 程度）。"
./.venv-vc/bin/python -c "import torch; print('MPS（GPU）利用可:', torch.backends.mps.is_available())"
