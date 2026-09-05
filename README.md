---
title: AutoCutter PRO
emoji: ✂️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: 無音・フィラーを自動カットし、声色を変換する動画編集ツール
---

# AutoCutter PRO

無音カット・フィラーカット・声色変換を自動で行う動画編集ツール。
テロップ生成は既存の [04.subtitle（AI Subtitle）](../04.subtitle) と同じ Whisper ベースのロジックを流用している。

## できること

| 機能 | 内容 |
|---|---|
| 無音カット | 音量が閾値（既定 -38dBFS）以下の状態が一定秒数続く区間を自動検出してカット |
| フィラーカット | Whisper の単語タイムスタンプから「えー」「あのー」等を検出してカット |
| 声色変換 | 身バレ防止のためのピッチシフト。話速を維持する高品質方式（librosa）と簡易方式（pydub） |
| テロップ出力 | カット後のタイミングにズレを補正した SRT / ASS を出力 |
| マージン調整 | カット前後に余白を残し、ブツ切り感を防ぐ |

## セットアップ

ffmpeg と Python 3.10〜3.12 が必要（openai-whisper が依存する torch が 3.13 以降に未対応）。
システムの `python3` が 3.13+ でも、3.12 を別途入れておけば `setup.sh` が自動で見つける。

```bash
brew install ffmpeg python@3.12
```

```bash
./setup.sh
```

`PYTHON=/path/to/python3.11 ./setup.sh` のように使う Python を明示指定することもできる。

## 使い方

### GUI（Streamlit）

```bash
./.venv/bin/streamlit run app.py
```

動画をアップロード →「解析する」でカット箇所とテロップを確認 →「動画を書き出す」。
テロップは書き出し前に表内で直接編集できる。

### CLI

```bash
./.venv/bin/python cli.py input.mp4 -o output.mp4 --srt output.srt --pitch 4
```

カット箇所だけ先に確認したいときは `--dry-run` を付ける。

```bash
./.venv/bin/python cli.py input.mp4 --dry-run
```

主なオプション:

| オプション | 既定 | 説明 |
|---|---|---|
| `--threshold` | -38 | 無音とみなす音量（dBFS）。切りすぎるときは下げる |
| `--min-silence` | 0.5 | 無音とみなす最短秒数 |
| `--margin` | 0.08 | カット前後に残す余白（秒） |
| `--pitch` | 0 | ピッチ変化量（半音）。±3〜5 が実用的 |
| `--fillers` | 既定リスト | カットする単語をカンマ区切りで指定 |
| `--no-silence` / `--no-filler` | — | 各カットを無効化 |
| `--model` | base | Whisper モデル（tiny / base / small / medium） |

## Web で使う（Hugging Face Spaces）

ブラウザ上で動画をアップロードして編集できるように、Docker SDK の Space としてデプロイする。
`main` に push すると GitHub Actions が Space へ自動同期する（04.subtitle と同じ仕組み）。

### 初回だけ必要な設定

1. **Space を作る** — https://huggingface.co/new-space
   - Owner: `AutoCraft502` / Space name: `autocutter-pro`
   - SDK: **Docker**（Blank template）
   - 別の名前にする場合は、GitHub リポジトリの Settings → Secrets and variables → Actions → Variables に
     `HF_USER` / `HF_SPACE` を登録すれば、ワークフローがそちらを見る。

2. **HF アクセストークンを作る** — https://huggingface.co/settings/tokens
   - Type: **Write**（Space への push に必要）

3. **GitHub にトークンを登録する** — リポジトリの
   Settings → Secrets and variables → Actions → New repository secret
   - Name: `HF_TOKEN` / Secret: 上で作ったトークン

4. Actions タブから **Sync to Hugging Face Hub** を手動実行するか、`main` に何か push する。

### 構成

| ファイル | 役割 |
|---|---|
| `Dockerfile` | Python 3.12 + ffmpeg。CPU 版 torch と Whisper base モデルを焼き込む |
| `.streamlit/config.toml` | アップロード上限 1000MB、ダークテーマ |
| `.github/workflows/sync_to_huggingface.yml` | main への push で Space へ同期 |

### 無料枠での制約

HF Spaces の無料枠は **CPU 2 コア / メモリ 16GB**。GPU は無い。

- Whisper は CPU 実行になるため、`medium` 以上は実用的でない。**`tiny` か `base`** を選ぶこと
- 動画のエンコードも CPU なので、**10 分程度までの動画**を想定
- Space はアクセスが無いとスリープし、次回起動に時間がかかる
- ストレージは揮発性。アップロードした動画も書き出した動画も再起動で消えるため、
  **書き出した動画は必ずダウンロードすること**


## モジュール構成

```
autocutter/
├── audio_analyzer.py   無音検知・フィラー検知・Keep List 算出・字幕リマップ
├── voice_changer.py    ピッチシフト（librosa / pydub）
├── video_editor.py     音声抽出・カット・結合・エンコード（moviepy 1.x/2.x 両対応）
├── transcriber.py      Whisper ラッパー（openai-whisper / faster-whisper）
├── subtitle_utils.py   SRT / ASS 出力（04.subtitle から流用）
└── pipeline.py         上記を設計書のフロー順に繋ぐオーケストレータ
app.py                  Streamlit UI
cli.py                  コマンドライン版
tests/                  区間演算・字幕リマップの単体テスト
```

## 処理フロー

```
入力動画
  └─ 音声抽出 (moviepy → wav)
       ├─ Whisper 音声認識（単語タイムスタンプ付き）
       │    └─ フローA: フィラー区間を検出
       ├─ pydub.silence
       │    └─ フローB: 無音区間を検出
       ├─ マージン適用 → 統合 → Keep List 算出
       ├─ 声色変換（ピッチシフト）
       └─ 映像カット + 変換音声を合成 → mp4
            └─ 字幕をカット後タイムラインへリマップ → SRT / ASS
```

## 既存アプリとの連携

既に 04.subtitle で音声認識済みの結果があれば、再解析せずに使い回せる。

```python
from autocutter import pipeline

result = pipeline.analyze(
    "input.mp4",
    pipeline.CutSettings(pitch_shift_semitones=4),
    work_dir="./work",
    whisper_result=existing_result,   # 04.subtitle の transcribe() 結果をそのまま渡す
)
```

`detect_fillers()` は `{"segments": [...]}` でもセグメントのリストでも受け付ける。
単語タイムスタンプが無い結果の場合は、セグメント全体がフィラーのみのケースだけを
保守的にカットする（誤カット防止）。

## テスト

```bash
./run_tests.sh
```

区間演算・字幕リマップ・SRT/ASS 出力は重い依存なしで実行できる（26 件）。
セットアップ前でも、システムの python3 が 3.13+ でも通る。

`python3 -m unittest discover -s tests` を直接叩く場合は、必ずこのプロジェクトの
ディレクトリに `cd` してから実行すること（`tests` は相対パスで解決されるため、
別ディレクトリからだと `ImportError: Start directory is not importable: 'tests'` になる）。

## 注意点

- 声色変換の「簡易方式（pydub）」はピッチと同時に再生速度も変わるため、映像とズレる。
  動画書き出しでは「高品質（librosa）」を使うこと。ズレを検出した場合は書き出し時にエラーになる。
- ピッチ変化量は ±12 半音に制限している（それ以上は聞き取れなくなるため）。
