"""
AutoCutter PRO — 自動編集＆声色変換アプリ（Streamlit UI）

無音カット・フィラーカット・声色変換を行い、ズレを補正したテロップ（SRT/ASS）も出力する。
起動:  streamlit run app.py
"""

import os
import shutil
import sys
import tempfile

import streamlit as st

# PyInstaller の --noconsole 時に stdout/stderr が None になる対策（04.subtitle と同じ）
class DummyStream:
    def write(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass

if sys.stdout is None:
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = DummyStream()

# 同梱 ffmpeg を優先的に見つけられるように PATH を通す
if getattr(sys, "frozen", False):
    os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ["PATH"]
else:
    os.environ["PATH"] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ["PATH"]

from autocutter import audio_analyzer, pipeline, subtitle_utils, video_editor  # noqa: E402

st.set_page_config(page_title="AutoCutter PRO", page_icon="✂️", layout="wide")


# --------------------------------------------------------------------------
# ユーティリティ
# --------------------------------------------------------------------------

def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_work_dir() -> str:
    """このセッション専用の作業ディレクトリ。"""
    if "work_dir" not in st.session_state:
        st.session_state["work_dir"] = tempfile.mkdtemp(prefix="autocutter_", dir=None)
    os.makedirs(st.session_state["work_dir"], exist_ok=True)
    return st.session_state["work_dir"]


def save_uploaded_file(uploaded_file) -> str:
    work_dir = get_work_dir()
    path = os.path.join(work_dir, uploaded_file.name)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path


def format_hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def reset_analysis():
    for key in ("result", "output_video"):
        st.session_state.pop(key, None)


# --------------------------------------------------------------------------
# サイドバー：処理設定
# --------------------------------------------------------------------------

st.title("✂️ AutoCutter PRO")
st.caption(
    "無音・フィラーを自動カットし、声色を変えて書き出す動画・音声編集ツール。"
    "動画（mp4 / mov など）と音声のみ（mp3 / m4a / wav / flac / ogg など）に対応。"
)

with st.sidebar:
    st.header("⚙️ 処理設定")

    st.subheader("🔇 無音カット")
    remove_silence = st.checkbox("無音区間をカットする", value=True)
    silence_threshold_db = st.slider(
        "無音とみなす音量（dBFS）", -60.0, -10.0, -38.0, 1.0,
        help="小さい値ほど「本当に静か」な部分だけを切ります。切りすぎるときは下げてください。",
        disabled=not remove_silence,
    )
    min_silence_len = st.slider(
        "無音とみなす最短の長さ（秒）", 0.1, 3.0, 0.5, 0.1,
        disabled=not remove_silence,
    )

    st.subheader("🗣️ フィラーカット")
    remove_fillers = st.checkbox("フィラー（えー・あのー等）をカットする", value=True)
    filler_text = st.text_area(
        "カットする単語（カンマ区切り）",
        value="、".join(audio_analyzer.DEFAULT_FILLER_WORDS_JA),
        height=100,
        disabled=not remove_fillers,
    )

    st.subheader("🎚️ マージン")
    margin = st.slider(
        "カット前後に残す余白（ミリ秒）", 0, 500, 80, 10,
        help="ブツ切り感を防ぎます。大きくすると自然になりますが、カット量は減ります。",
    ) / 1000.0

    st.subheader("🎤 声色変換")
    pitch_shift = st.slider(
        "ピッチ（半音）", -12.0, 12.0, 0.0, 0.5,
        help="+ で高く、- で低くなります。±3〜5 半音あたりが身バレ防止と聞き取りやすさのバランス点です。",
    )
    pitch_method = st.radio(
        "変換方式",
        ["librosa", "pydub"],
        format_func=lambda m: "高品質（話速を維持）" if m == "librosa" else "簡易・高速（話速も変化）",
        disabled=pitch_shift == 0,
        help="動画に使う場合は「高品質」を選んでください。簡易方式は音声の長さが変わるため映像とズレます。",
    )

    st.divider()
    st.subheader("🧠 音声認識")
    model_size = st.selectbox("モデル", ["tiny", "base", "small", "medium"], index=1)
    language = st.selectbox(
        "言語", ["ja", "en", "zh", "ko", "pt"], index=0,
        format_func=lambda c: {"ja": "日本語", "en": "English", "zh": "中文", "ko": "한국어", "pt": "Português"}[c],
    )


# --------------------------------------------------------------------------
# メイン：アップロード → 解析 → 書き出し
# --------------------------------------------------------------------------

uploaded_file = st.file_uploader(
    "動画 / 音声ファイルをアップロード",
    type=[
        "mp4", "mov", "mkv", "avi", "m4v",
        "mp3", "m4a", "wav", "flac", "ogg", "oga", "opus", "aac", "aiff", "wma",
    ],
    on_change=reset_analysis,
)

if uploaded_file is None:
    st.info("動画（mp4 / mov など）または音声（mp3 / m4a / wav など）をアップロードすると解析できます。")
    st.stop()

media_path = save_uploaded_file(uploaded_file)
is_audio = video_editor.is_audio_only(media_path)

col_video, col_action = st.columns([2, 1])
with col_video:
    if is_audio:
        st.audio(media_path)
    else:
        st.video(media_path)

filler_words = [w.strip() for w in filler_text.replace("、", ",").split(",") if w.strip()]

settings = pipeline.CutSettings(
    remove_silence=remove_silence,
    silence_threshold_db=silence_threshold_db,
    min_silence_len=min_silence_len,
    remove_fillers=remove_fillers,
    filler_words=filler_words,
    margin=margin,
    pitch_shift_semitones=pitch_shift,
    pitch_method=pitch_method,
    model_size=model_size,
    language=language,
)

with col_action:
    st.markdown("### 1. 解析")
    st.caption("音声認識 → 無音・フィラー検出 → カットリスト作成")
    if st.button("🔍 解析する", type="primary", use_container_width=True):
        progress = st.progress(0.0, text="準備中...")

        def on_progress(ratio, message):
            progress.progress(min(1.0, ratio), text=message)

        try:
            st.session_state["result"] = pipeline.analyze(
                media_path, settings, get_work_dir(), progress_callback=on_progress
            )
            st.session_state.pop("output_video", None)
        except Exception as e:
            progress.empty()
            st.error(f"解析に失敗しました: {e}")
        else:
            progress.empty()
            st.success("解析完了")

result = st.session_state.get("result")
if result is None:
    st.stop()

# --- 解析サマリ -----------------------------------------------------------
st.divider()
st.header("📊 解析結果")

c1, c2, c3, c4 = st.columns(4)
c1.metric("元の長さ", format_hms(result.original_duration))
c2.metric("編集後", format_hms(result.new_duration))
c3.metric("カット量", format_hms(result.removed_duration), f"-{result.removed_ratio * 100:.1f}%")
c4.metric("カット箇所", f"{len(result.silence_cuts) + len(result.filler_cuts)} 箇所")

with st.expander(f"🔇 無音カット {len(result.silence_cuts)} 箇所 / 🗣️ フィラーカット {len(result.filler_cuts)} 箇所"):
    tab_silence, tab_filler = st.tabs(["無音", "フィラー"])
    with tab_silence:
        st.dataframe(
            [{"開始": format_hms(s), "終了": format_hms(e), "長さ(秒)": round(e - s, 2)}
             for s, e in result.silence_cuts],
            use_container_width=True,
        )
    with tab_filler:
        st.dataframe(
            [{"開始": format_hms(s), "終了": format_hms(e), "長さ(秒)": round(e - s, 2)}
             for s, e in result.filler_cuts],
            use_container_width=True,
        )

# --- テロップ編集 ---------------------------------------------------------
st.subheader("📝 テロップ（カット後のタイミングに補正済み）")
edited = st.data_editor(
    result.subtitles,
    column_config={
        "start": st.column_config.NumberColumn("開始(秒)", format="%.2f"),
        "end": st.column_config.NumberColumn("終了(秒)", format="%.2f"),
        "text": st.column_config.TextColumn("テキスト", width="large"),
    },
    num_rows="dynamic",
    use_container_width=True,
    key="subtitle_editor",
)

col_srt, col_ass = st.columns(2)
with col_srt:
    st.download_button(
        "⬇️ SRT をダウンロード",
        data=subtitle_utils.create_srt_content(edited),
        file_name="autocutter.srt",
        mime="text/plain",
        use_container_width=True,
    )
with col_ass:
    st.download_button(
        "⬇️ ASS をダウンロード",
        data=subtitle_utils.create_ass_content(edited),
        file_name="autocutter.ass",
        mime="text/plain",
        use_container_width=True,
    )

# --- 書き出し -------------------------------------------------------------
st.divider()
st.header("🎬 2. 書き出し")

if pitch_shift and pitch_method == "pydub":
    st.warning("簡易方式は音声の長さが変わるため映像とズレます。動画書き出しには「高品質」を選んでください。")

if st.button("🎬 動画 / 音声を書き出す", type="primary"):
    progress = st.progress(0.0, text="準備中...")

    def on_progress(ratio, message):
        progress.progress(min(1.0, ratio), text=message)

    ext = video_editor.supported_output_extension(media_path) if is_audio else ".mp4"
    output_path = os.path.join(get_work_dir(), f"autocutter_output{ext}")
    try:
        # 出力形式が書き出し時に変わることがあるので、実際のパスを受け取る
        output_path = pipeline.render(
            media_path, result, settings, output_path, get_work_dir(), on_progress
        )
    except Exception as e:
        progress.empty()
        st.error(f"書き出しに失敗しました: {e}")
    else:
        progress.empty()
        st.session_state["output_video"] = output_path
        st.success("書き出し完了")

if st.session_state.get("output_video"):
    output_path = st.session_state["output_video"]
    if is_audio:
        st.audio(output_path)
    else:
        st.video(output_path)
    with open(output_path, "rb") as f:
        st.download_button(
            f"⬇️ 編集済み{'音声' if is_audio else '動画'}をダウンロード",
            data=f.read(),
            file_name=os.path.basename(output_path),
            mime="audio/mpeg" if is_audio else "video/mp4",
            use_container_width=True,
        )

st.divider()
st.caption("AutoCutter PRO — 無音・フィラー自動カット / 声色変換 / テロップ生成")
