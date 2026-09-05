"""
AutoCutter PRO — 自動編集＆声色変換アプリ（Gradio UI / Hugging Face Spaces 用）

無音カット・フィラーカット・声色変換を行い、ズレを補正したテロップ（SRT/ASS）も出力する。
起動:  python app.py

ローカルでは Streamlit 版（streamlit_app.py）も使える。UI が違うだけで中身は同じ。
"""

from __future__ import annotations

import os
import shutil
import tempfile

# ZeroGPU（HF Spaces）で音声認識を GPU に載せるためのデコレータ。
# spaces は torch より先に import する必要があるため、他の import より前に置く。
#
# ZeroGPU は起動時に @spaces.GPU 付きの関数をスキャンし、1 つも無いと
# 「No @spaces.GPU function detected during startup」で起動に失敗する。
# 環境変数で条件分岐するとこの検出に引っかかるため、常に適用する。
# 公式ドキュメント曰く、このデコレータは ZeroGPU 以外の環境では効果を持たない。
try:
    import spaces

    # 音声認識だけを GPU 区間にする（動画エンコードは CPU 側で回す）
    gpu_task = spaces.GPU(duration=120)
    HAS_SPACES = True
except ImportError:  # spaces を入れていないローカル環境
    HAS_SPACES = False

    def gpu_task(fn):
        return fn


# ZeroGPU は呼び出しごとに GPU を割り当て直すので、モデルを使い回せない
IS_ZERO_GPU = HAS_SPACES and bool(os.environ.get("SPACE_ID"))

import gradio as gr

from autocutter import audio_analyzer, pipeline, subtitle_utils, transcriber, video_editor


LANGUAGES = {
    "日本語": "ja",
    "English": "en",
    "中文": "zh",
    "한국어": "ko",
    "Português": "pt",
}


# --------------------------------------------------------------------------
# ユーティリティ
# --------------------------------------------------------------------------

def format_hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def parse_fillers(text: str) -> list[str]:
    return [w.strip() for w in (text or "").replace("、", ",").split(",") if w.strip()]


@gpu_task
def run_transcribe(audio_path: str, model_size: str, language: str) -> dict:
    """音声認識だけを切り出した関数。ZeroGPU ではここだけが GPU を掴む。

    ZeroGPU は呼び出しごとに GPU を割り当て直すため、モデルをプロセス内に
    キャッシュして使い回すと 2 回目以降に壊れる。そこでキャッシュを切る。
    """
    return transcriber.transcribe(
        audio_path,
        model_size=model_size,
        language=language,
        word_timestamps=True,
        cache_model=not IS_ZERO_GPU,
    )


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

def analyze(
    video_path,
    audio_path_in,
    remove_silence,
    threshold_db,
    min_silence_len,
    remove_fillers,
    filler_text,
    margin_ms,
    pitch,
    model_size,
    language_label,
    progress=gr.Progress(),
):
    media_path = video_path or audio_path_in
    if not media_path:
        raise gr.Error("先に動画または音声ファイルをアップロードしてください。")

    settings = pipeline.CutSettings(
        remove_silence=remove_silence,
        silence_threshold_db=threshold_db,
        min_silence_len=min_silence_len,
        remove_fillers=remove_fillers,
        filler_words=parse_fillers(filler_text),
        margin=margin_ms / 1000.0,
        pitch_shift_semitones=pitch,
        model_size=model_size,
        language=LANGUAGES[language_label],
    )

    work_dir = tempfile.mkdtemp(prefix="autocutter_")

    try:
        # 1. 音声抽出（この wav は後段の解析・声色変換で使い回す）
        progress(0.05, desc="音声を抽出中...")
        audio_path = os.path.join(work_dir, "source_audio.wav")
        video_editor.extract_audio(media_path, audio_path)

        # 2. 音声認識（ZeroGPU ではここだけ GPU）
        progress(0.20, desc=f"音声認識中...（model={model_size}）")
        whisper_result = run_transcribe(audio_path, model_size, settings.language)

        # 3. カット区間の算出と字幕リマップ
        progress(0.70, desc="カット区間を算出中...")
        result = pipeline.analyze(
            media_path, settings, work_dir, whisper_result=whisper_result
        )
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise gr.Error(f"解析に失敗しました: {e}") from e

    stats = (
        f"### 解析結果\n"
        f"| 項目 | 値 |\n|---|---|\n"
        f"| 元の長さ | {format_hms(result.original_duration)} |\n"
        f"| 編集後 | {format_hms(result.new_duration)} |\n"
        f"| カット量 | {format_hms(result.removed_duration)} "
        f"（{result.removed_ratio * 100:.1f}%） |\n"
        f"| 無音カット | {len(result.silence_cuts)} 箇所 |\n"
        f"| フィラーカット | {len(result.filler_cuts)} 箇所 |\n"
    )

    cuts = [
        [kind, format_hms(s), format_hms(e), round(e - s, 2)]
        for kind, segs in (("無音", result.silence_cuts), ("フィラー", result.filler_cuts))
        for s, e in segs
    ]
    cuts.sort(key=lambda row: row[1])

    subs = [[round(s["start"], 2), round(s["end"], 2), s["text"]] for s in result.subtitles]

    kind = "音声" if result.is_audio_only else "動画"
    stats = stats.replace("### 解析結果", f"### 解析結果（{kind}）")

    state = {
        "media_path": media_path,
        "work_dir": work_dir,
        "result": result,
        "settings": settings,
    }
    return stats, cuts, subs, state


# --------------------------------------------------------------------------
# 書き出し
# --------------------------------------------------------------------------

def _rows_to_segments(rows) -> list[dict]:
    """Dataframe の中身（DataFrame でも list でも）を字幕 dict のリストにする。"""
    if rows is None:
        return []
    if hasattr(rows, "values"):
        rows = rows.values.tolist()

    segments = []
    for row in rows:
        if row is None or len(row) < 3:
            continue
        start, end, text = row[0], row[1], row[2]
        if start is None or end is None or not str(text).strip():
            continue
        segments.append({"start": float(start), "end": float(end), "text": str(text)})
    return segments


def export_subtitles(state, sub_rows):
    if not state:
        raise gr.Error("先に解析を実行してください。")

    segments = _rows_to_segments(sub_rows)
    if not segments:
        raise gr.Error(
            "書き出せるテロップがありません。"
            "音声が認識されなかった可能性があります（言語設定を確認してください）。"
        )

    work_dir = state["work_dir"]
    srt_path = os.path.join(work_dir, "autocutter.srt")
    ass_path = os.path.join(work_dir, "autocutter.ass")

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(subtitle_utils.create_srt_content(segments))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(subtitle_utils.create_ass_content(segments))

    return [srt_path, ass_path]


def render_media(state, progress=gr.Progress()):
    """編集後のファイルを書き出す。返り値は (動画, 音声) で、該当しない方は None。"""
    if not state:
        raise gr.Error("先に解析を実行してください。")

    result = state["result"]
    settings = state["settings"]
    work_dir = state["work_dir"]
    media_path = state["media_path"]

    if result.is_audio_only:
        ext = video_editor.supported_output_extension(media_path)
    else:
        ext = ".mp4"
    output_path = os.path.join(work_dir, f"autocutter_output{ext}")

    def report(ratio, message):
        progress(ratio, desc=message)

    try:
        # 出力形式が書き出し時に変わることがあるので、実際のパスを受け取る
        output_path = pipeline.render(
            media_path, result, settings, output_path, work_dir, report
        )
    except Exception as e:
        raise gr.Error(f"書き出しに失敗しました: {e}") from e

    if result.is_audio_only:
        return gr.update(value=None, visible=False), gr.update(value=output_path, visible=True)
    return gr.update(value=output_path, visible=True), gr.update(value=None, visible=False)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

with gr.Blocks(title="AutoCutter PRO") as demo:
    state = gr.State()

    gr.Markdown(
        "# ✂️ AutoCutter PRO\n"
        "無音・フィラーを自動カットし、声色を変えて書き出す動画・音声編集ツール。"
        "カット後のタイミングに補正したテロップ（SRT / ASS）も出力します。\n\n"
        "動画（mp4 / mov など）と、音声のみ（mp3 / m4a / wav / flac / ogg / aac など）の"
        "どちらにも対応しています。"
    )

    with gr.Row():
        with gr.Column(scale=1):
            with gr.Tabs():
                with gr.Tab("🎬 動画"):
                    video_in = gr.Video(label="動画をアップロード", sources=["upload"])
                with gr.Tab("🎵 音声のみ"):
                    audio_in = gr.Audio(
                        label="音声をアップロード（mp3 / m4a / wav / flac / ogg / aac など）",
                        sources=["upload"],
                        type="filepath",
                    )

            with gr.Accordion("🔇 無音カット", open=True):
                remove_silence = gr.Checkbox(label="無音区間をカットする", value=True)
                threshold_db = gr.Slider(
                    -60, -10, value=-38, step=1,
                    label="無音とみなす音量（dBFS）",
                    info="小さい値ほど「本当に静か」な部分だけを切ります。切りすぎるときは下げてください。",
                )
                min_silence_len = gr.Slider(
                    0.1, 3.0, value=0.5, step=0.1, label="無音とみなす最短の長さ（秒）"
                )

            with gr.Accordion("🗣️ フィラーカット", open=True):
                remove_fillers = gr.Checkbox(
                    label="フィラー（えー・あのー等）をカットする", value=True
                )
                filler_text = gr.Textbox(
                    label="カットする単語（カンマ区切り）",
                    value="、".join(audio_analyzer.DEFAULT_FILLER_WORDS_JA),
                    lines=3,
                )

            with gr.Accordion("🎚️ マージン / 🎤 声色変換", open=True):
                margin_ms = gr.Slider(
                    0, 500, value=80, step=10,
                    label="カット前後に残す余白（ミリ秒）",
                    info="ブツ切り感を防ぎます。大きくすると自然になりますが、カット量は減ります。",
                )
                pitch = gr.Slider(
                    -12, 12, value=0, step=0.5,
                    label="ピッチ（半音）",
                    info="+ で高く、- で低く。±3〜5 が身バレ防止と聞き取りやすさのバランス点です。",
                )

            with gr.Accordion("🧠 音声認識", open=False):
                model_size = gr.Dropdown(
                    ["tiny", "base", "small", "medium"], value="base", label="モデル",
                    info="大きいほど精度は上がりますが遅くなります。",
                )
                language_label = gr.Dropdown(
                    list(LANGUAGES.keys()), value="日本語", label="言語"
                )

            analyze_btn = gr.Button("🔍 解析する", variant="primary")

        with gr.Column(scale=1):
            stats_out = gr.Markdown("動画または音声をアップロードして「解析する」を押してください。")

            cuts_out = gr.Dataframe(
                headers=["種別", "開始", "終了", "長さ(秒)"],
                label="カット箇所",
                interactive=False,
                wrap=True,
            )

            subs_out = gr.Dataframe(
                headers=["開始(秒)", "終了(秒)", "テキスト"],
                label="テロップ（カット後のタイミングに補正済み・編集可）",
                interactive=True,
                wrap=True,
            )

            with gr.Row():
                srt_btn = gr.Button("📝 テロップを書き出す")
                render_btn = gr.Button("🎬 動画 / 音声を書き出す", variant="primary")

            subs_files = gr.File(label="SRT / ASS", file_count="multiple")
            video_out = gr.Video(label="編集済み動画", visible=True)
            audio_out = gr.Audio(label="編集済み音声", visible=False)

    gr.Markdown(
        "---\n"
        "**注意**: ストレージは揮発性です。書き出した動画・テロップは必ずダウンロードしてください。\n"
        "無料枠は CPU 2 コアのため、モデルは `tiny` / `base`、動画は 10 分程度までを推奨します。"
    )

    analyze_btn.click(
        analyze,
        inputs=[
            video_in, audio_in, remove_silence, threshold_db, min_silence_len,
            remove_fillers, filler_text, margin_ms, pitch, model_size, language_label,
        ],
        outputs=[stats_out, cuts_out, subs_out, state],
    )
    srt_btn.click(export_subtitles, inputs=[state, subs_out], outputs=[subs_files])
    render_btn.click(render_media, inputs=[state], outputs=[video_out, audio_out])


if __name__ == "__main__":
    # Gradio 6 では theme は launch() 側で指定する
    demo.queue().launch(
        theme=gr.themes.Soft(),
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
    )
