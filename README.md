---
title: AutoCutter PRO
emoji: ✂️
colorFrom: indigo
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
short_description: 無音・フィラーを自動カットし、声色を変換する動画編集ツール
---

# AutoCutter PRO

無音カット・フィラーカット・声色変換を自動で行う動画・音声編集ツール。
テロップ生成は既存の [04.subtitle（AI Subtitle）](../04.subtitle) と同じ Whisper ベースのロジックを流用している。

## できること

| 機能 | 内容 |
|---|---|
| 無音カット | 素材の平均音量を基準に閾値を自動調整し、一定秒数続く無音区間を検出してカット |
| フィラーカット | Whisper の単語タイムスタンプから「えー」「あのー」等を検出してカット。1 文字ずつに分割された認識結果にも対応 |
| 声色変換（信号処理） | ピッチとフォルマントを同時に動かすプリセット。追加導入不要で速い |
| 声色変換（AI） | seed-vc による声質変換。**別人の声**に置き換える。話す長さ・間・抑揚は元のまま |
| テロップ出力 | カット後のタイミングにズレを補正した SRT / ASS を出力 |
| マージン調整 | カット前後に余白を残し、ブツ切り感を防ぐ |

## 対応フォーマット

| 種別 | 拡張子 |
|---|---|
| 動画 | `mp4` `mov` `mkv` `avi` `m4v` |
| 音声 | `mp3` `m4a` `wav` `flac` `ogg` `oga` `opus` `aac` `aiff` `wma` など |

音声のみのファイルを入れた場合は、映像を扱わず音声だけをカット・変換して
**入力と同じ形式で**書き出す（その形式でエンコードできない ffmpeg ビルドでは
自動的に `m4a` へ切り替わる）。テロップの出力は動画・音声どちらでも同じ。

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

### GUI（Gradio / Hugging Face Spaces と同じもの）

```bash
./run_local.sh
```

起動を待ってブラウザが自動で開く。直接動かす場合は次のとおり。

```bash
./.venv/bin/python app.py
```

http://localhost:7860 が開く。「動画」「音声のみ」のタブから素材をアップロード
→「解析する」でカット箇所とテロップを確認 →「動画 / 音声を書き出す」。
テロップは書き出し前に表内で直接編集できる。

### GUI（Streamlit / ローカル専用）

```bash
./.venv/bin/streamlit run streamlit_app.py
```

同じ処理を Streamlit の UI で操作するもの。中身は `autocutter/` を共有しているので挙動は同じ。

### CLI

```bash
./.venv/bin/python cli.py input.mp4 -o output.mp4 --srt output.srt --pitch 4
```

音声のみのファイルも同じように渡せる。出力を省略すると入力と同じ形式になる。

```bash
./.venv/bin/python cli.py input.m4a --srt output.srt --pitch 4
```

カット箇所だけ先に確認したいときは `--dry-run` を付ける。

```bash
./.venv/bin/python cli.py input.mp4 --dry-run
```

主なオプション:

| オプション | 既定 | 説明 |
|---|---|---|
| `--sensitivity` | 16 | 平均音量から何 dB 下を無音とみなすか。カットされ過ぎるときは大きくする |
| `--threshold` | （自動） | 無音の dBFS を固定値で指定。指定すると `--sensitivity` は無視される |
| `--min-silence` | 0.5 | 無音とみなす最短秒数 |
| `--margin` | 0.08 | カット前後に残す余白（秒） |
| `--pitch` | 0 | ピッチ変化量（半音）。±3〜5 が実用的 |
| `--fillers` | 既定リスト | カットする単語をカンマ区切りで指定 |
| `-o` | 入力と同じ形式 | 出力パス。音声入力では拡張子で出力形式が決まる |
| `--no-silence` / `--no-filler` | — | 各カットを無効化 |
| `--model` | base | Whisper モデル（tiny / base / small / medium） |

## Web で使う（Hugging Face Spaces）

ブラウザ上で動画をアップロードして編集できるように、**Gradio SDK** の Space としてデプロイする。
`main` に push すると GitHub Actions が Space へ自動同期する（04.subtitle と同じ仕組み）。

> **なぜ Docker SDK ではないのか**
> 2026 年 7 月頃の方針変更で、**Docker Space は有料プラン（PRO / 月 $9）専用**になった。
> 無料アカウントで作れるのは Gradio SDK の Space なので、UI を Gradio で用意している。
> 既存の Docker Space（04.subtitle の `ai-subtitle` など）は変更前のものがそのまま残る。
> リポジトリの `Dockerfile` は、自前サーバーや PRO で Docker として動かしたいとき用に残してある。

### 初回だけ必要な設定

1. **Space を作る** — https://huggingface.co/new-space
   - Owner: `AutoCraft502` / Space name: `autocutter-pro`
   - SDK: **Gradio**（Blank template）
   - Hardware: 無料枠（CPU Basic か ZeroGPU）
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
| `README.md` の frontmatter | `sdk: gradio` / `app_file: app.py` を Space に伝える |
| `packages.txt` | Space に ffmpeg を入れる（moviepy・pydub・whisper が必要とする） |
| `requirements.txt` | Python 依存。Space はこれを見て環境を作る |
| `.github/workflows/sync_to_huggingface.yml` | main への push で Space へ同期 |
| `Dockerfile` | Space では未使用。自前ホスティング / PRO の Docker Space 用 |

### ZeroGPU について

Hardware に **ZeroGPU** を選んだ場合、音声認識だけが GPU で動く（動画エンコードは CPU のまま）。

実装上の注意が 2 つある。

1. ZeroGPU は起動時に `@spaces.GPU` 付きの関数をスキャンし、1 つも見つからないと
   `No @spaces.GPU function detected during startup` で起動に失敗する。
   環境変数で条件分岐してデコレータを付け外しするとこの検出に引っかかるため、
   **常に適用している**。公式ドキュメントの通り、このデコレータは ZeroGPU 以外の
   環境では効果を持たないので、ローカル実行でも問題ない。
2. ZeroGPU は呼び出しごとに GPU を割り当て直すため、前回の割り当てに紐づいた
   モデルを使い回せない。Space 上でだけ Whisper モデルのプロセス内キャッシュを切っている
   （`transcriber.load_model(cache=False)`）。

**GPU クォータに注意**: 無料アカウントの ZeroGPU は **1 日あたり 5 分**、
未ログインの訪問者は 2 分まで。音声認識は速くなるが、使えるのは 1 日数本程度。
本数を稼ぎたい場合は Space の Settings で **CPU Basic** に切り替えるとクォータ制限が無くなる
（その場合は全て CPU で動き、`tiny` / `base` 推奨）。

### 無料枠での制約

- Whisper は CPU 実行だと重いので、CPU Basic なら **`tiny` か `base`** を選ぶこと
- 動画のエンコードは常に CPU なので、**10 分程度までの動画**を想定
- Space はアクセスが無いとスリープし、次回起動に時間がかかる
- ストレージは揮発性。アップロードした動画も書き出した動画も再起動で消えるため、
  **書き出した動画は必ずダウンロードすること**


## モジュール構成

```
autocutter/
├── audio_analyzer.py   無音検知・フィラー検知・Keep List 算出・字幕リマップ
├── voice_changer.py    ピッチシフト（librosa / pydub）
├── video_editor.py     音声抽出・カット・結合・エンコード（動画は moviepy、音声のみは pydub）
├── transcriber.py      Whisper ラッパー（openai-whisper / faster-whisper）
├── subtitle_utils.py   SRT / ASS 出力（04.subtitle から流用）
└── pipeline.py         上記を設計書のフロー順に繋ぐオーケストレータ
├── ai_voice.py         AI 声質変換（seed-vc を別プロセスで呼ぶ・任意導入）
├── ffmpeg_tools.py     ffmpeg の場所を一元管理（moviepy と pydub で揃える）
app.py                  Gradio UI（Hugging Face Spaces のエントリポイント）
streamlit_app.py        Streamlit UI（ローカル用）
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

区間演算・字幕リマップ・SRT/ASS 出力・メディア種別判定・声色プリセット・
AI 変換の可用性判定は
重い依存なしで実行できる（62 件）。
セットアップ前でも、システムの python3 が 3.13+ でも通る。

`python3 -m unittest discover -s tests` を直接叩く場合は、必ずこのプロジェクトの
ディレクトリに `cd` してから実行すること（`tests` は相対パスで解決されるため、
別ディレクトリからだと `ImportError: Start directory is not importable: 'tests'` になる）。

## カットされ過ぎる / されなさすぎるとき

無音の閾値は既定で **素材の平均音量から 16 dB 下** に自動設定される。
固定値（例: -38 dBFS）にすると、小さく録れた素材では喋っている部分まで
無音と判定されてしまうため。

実測例（平均 -34.9 dBFS の 18 秒の録音）:

| 閾値 | 結果 |
|---|---|
| -38 dBFS（固定） | 18.07s → **3.47s**（80.8% カット。喋りごと消える） |
| -50.9 dBFS（自動・16 dB 下） | 18.07s → 11.59s（35.9% カット） |
| -54.9 dBFS（自動・20 dB 下） | 18.07s → 12.21s（32.4% カット） |

- **カットされ過ぎる** → 「感度」を大きくする（20〜25 など）
- **カットが足りない** → 「感度」を小さくする（10〜13 など）

6 割以上カットされた場合は UI と CLI が警告を出す。

### フィラーが検出されないとき

Whisper は既定では言い淀みを整形して落としてしまう。本アプリは
`initial_prompt` でフィラーごと書き起こすよう促しているが、それでも
拾えないことがある。モデルを `base` 以上にすると改善しやすい。

実測例（同じ録音）:

```
プロンプトなし: こんにちは、朝切りと申します。今日はよろしくお願いします。今、アプリを…
プロンプトあり: えー、こんにちは、朝切りと申します。… えーと、今アプリを…
```

なお日本語の単語タイムスタンプは `'えー'` `'と、'` のように割れることがあるため、
連続する単語をつなげて照合している（最長一致）。

## 声色変換について

声の性別・年齢の印象を決めているのはピッチ（声の高さ）だけではなく
**フォルマント**（声道の共鳴。体格に対応する）である。ピッチだけ動かすと
テープの早回しのような不自然な声になるため、2 つを独立に操作している。

プリセットを選ぶだけで両方が設定される。

| プリセット | 目標の声の高さ | フォルマント |
|---|---|---|
| そのまま（変換しない） | — | 1.00 |
| 女性の声 | 200 Hz | 1.18 |
| 高めの女性の声 | 240 Hz | 1.26 |
| 子供の声 | 290 Hz | 1.38 |
| 太い男の声 | 85 Hz | 0.84 |
| 低い男の声 | 100 Hz | 0.90 |
| 年配の男性の声 | 110 Hz | 0.95 |
| 軽い匿名化（自然さ優先） | — | 1.07 |

ピッチは半音数の固定値ではなく **目標の高さ** で指定している。解析時に話者の
基本周波数（F0）を測り、そこから必要な変化量を計算する。相対的な半音数だと
元の声の高さで着地点が変わってしまうため。

例: F0 が 68 Hz の低い声に「女性の声」を適用すると +18.6 半音（68 → 200 Hz）。
同じプリセットでも F0 が 150 Hz の声なら +5.0 半音で済む。

「変化の強さ」で効き具合を一括調整できる（0 で無変換、1.0 が既定）。
細かく詰めたい場合は「手動で調整する」を選ぶとピッチとフォルマントを個別に操作できる。

### AI 声質変換（別人の声にする）

信号処理では届かない場合、**seed-vc** による AI 声質変換を使える。参照音声を
1 つ渡すだけで学習不要でその声に変換でき、**話す長さ・間・抑揚は元のまま**
保たれるため、カット結果や動画との同期をやり直す必要がない。

実測（F0 68 Hz の話者を女性の参照音声に変換）:

| | F0 | 長さ |
|---|---|---|
| 元の声 | 68.3 Hz | 18.03 秒 |
| 参照音声（女性） | 254.9 Hz | — |
| **変換後** | **246.2 Hz** | 18.02 秒 |

参照音声との差は 8.7 Hz。信号処理方式（上限 217 Hz、しかも声質は元のまま）
とは別物の結果になる。

#### 導入

```bash
./setup_ai_voice.sh
```

seed-vc を `vendor/` に取得し、専用の仮想環境 `.venv-vc` を作る。本体とは
依存が非互換（numpy 1.26 / gradio 5 など）なので分離している。モデルは初回の
変換時に自動ダウンロードされる（1GB 程度）。**未導入でもアプリは普通に動き、
信号処理のプリセットが使える。**

#### 変換先の声

macOS では標準の音声合成から 8 種類（女性 3・男性 3・年配 2）を自動生成して
参照音声に使える。ただし**合成音声を参照にすると、その機械的な質感まで
引き継がれる**。自然な人の声の録音を参照にしたほうが結果は良い。

任意の音声ファイル（3 秒以上）をアップロードして、その声に変換できる。

```bash
./.venv/bin/python cli.py input.m4a --ai-voice Kyoko
./.venv/bin/python cli.py input.m4a --ai-voice /path/to/reference.wav
```

#### 抑揚（イントネーション）を保つ

seed-vc の `--f0-condition` は既定で無効になっており、そのままだと**元の抑揚が
3 割ほど平坦になって機械的な喋りに聞こえる**。本アプリでは既定で有効にしている。

実測（同じ音声・同じ参照音声）:

| 設定 | 抑揚の相関 | 抑揚の幅 |
|---|---|---|
| 元の声 | — | 23.5 |
| f0-condition なし | +0.809 | 16.3（3 割平坦） |
| **f0-condition あり（既定）** | **+0.994** | **22.2** |

速度と引き換えなので、急ぐときは UI の「元の抑揚を保つ」を外す
（CLI は `--no-keep-intonation`）。

なお Apple Silicon では seed-vc がこの機能で落ちる（F0 を float64 のまま MPS へ
送るため）。`ai_voice.ensure_mps_patch()` が実行前に毎回修正を当て直している。

#### 速度とライセンス

- Apple Silicon の MPS を使う。抑揚を保つ設定では**音声の長さの 4〜5 倍**
  （18 秒の音声で約 87 秒）、保たない場合は同じくらいの時間で終わる。
  品質は「拡散ステップ数」でも調整できる
- seed-vc は **GPL-3.0**。本体には取り込まず、別プロセス・別仮想環境として
  呼び出す構成にしている（`vendor/` と `.venv-vc/` は git 管理外）。
  個人利用では問題にならないが、成果物を配布・商用化する場合は
  ライセンスを確認すること

### 信号処理方式の限界

信号処理によるピッチ・フォルマント変換には限界がある。**元の声が低いほど、
女性や子供の音域には届きにくい**（音質を保てる上限を ±20 半音としているため）。

例えば F0 が 68 Hz の声の場合:

| プリセット | 到達する高さ | 目標 |
|---|---|---|
| 女性の声 | 200 Hz | 200 Hz ✅ |
| 高めの女性の声 | 217 Hz | 240 Hz ⚠️ |
| 子供の声 | 217 Hz | 290 Hz ⚠️ |

届かない場合は UI に警告が出る。「別人の声」に完全に置き換えたい場合は、
上の **AI 声質変換** を使うこと。

CLI では `--voice` で指定する。

```bash
./.venv/bin/python cli.py input.m4a --voice "女性の声" --voice-strength 1.2
```

```bash
./.venv/bin/python cli.py --list-voices
```

### 実装

フォルマントの移動は追加ライブラリ無しで行っている（librosa + numpy）。
STFT → ケプストラム法でスペクトル包絡を推定 → 包絡だけを周波数方向に伸縮 →
元の包絡との比を掛け直す、という手順。倍音の位置は動かさないので
ピッチは変わらない。librosa のピッチシフトはフォルマントも一緒に動かすため、
その分を差し引いてから目標の倍率に合わせている。

## 注意点

- 声色変換の「簡易方式（pydub）」はピッチと同時に再生速度も変わるため、映像とズレる。
  動画書き出しでは「高品質（librosa）」を使うこと。ズレを検出した場合は書き出し時にエラーになる。
- ピッチ変化量は ±12 半音、フォルマント倍率は 0.70〜1.45 に制限している
  （それ以上は聞き取れなくなるため）。
- ffmpeg は moviepy 同梱のバイナリを pydub にも使わせている。pydub は既定で
  PATH 上の `ffmpeg` を探すため、PATH に無い環境では「解析はできるのに
  書き出しだけ失敗する」という分かりにくい壊れ方をするのを防ぐため。
- 音声のみの入力は `pydub` で処理する。moviepy の `VideoFileClip` は映像トラックが
  無いファイルを開けないため、音声抽出は ffmpeg を直接呼んでいる。
