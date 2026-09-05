#!/usr/bin/env bash
# どのディレクトリから実行しても動くテストランナー
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m unittest discover -s tests -v
