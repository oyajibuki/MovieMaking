"""
video_editor.py — 編集・出力モジュール

「残す区間（Keep List）」に従って映像（または音声のみ）を切り出し、
声色変換した音声と合成して最終ファイルを書き出す。
moviepy 1.x / 2.x の API 差は薄いラッパーで吸収する。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable, Sequence

from . import ffmpeg_tools, voice_changer

Segment = tuple[float, float]

# 拡張子だけで音声と判断できるもの
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".oga",
    ".opus", ".wma", ".aiff", ".aif", ".alac", ".caf",
}

# pydub の export に渡す候補（拡張子 -> [(format, codec), ...]）。
# ffmpeg のビルドによって持っているエンコーダが違うので、前から順に試す。
# 例えば Homebrew の ffmpeg には libvorbis が入っていないことがある。
_EXPORT_FORMATS = {
    ".m4a": [("ipod", "aac")],
    ".mp4": [("ipod", "aac")],
    ".aac": [("adts", "aac")],
    ".mp3": [("mp3", None)],
    ".wav": [("wav", None)],
    ".flac": [("flac", None)],
    ".ogg": [("ogg", "libvorbis"), ("ogg", "libopus")],
    ".oga": [("ogg", "libvorbis"), ("ogg", "libopus")],
    ".opus": [("opus", "libopus")],
}

# どの ffmpeg ビルドでも使える最後の逃げ道
_FALLBACK_FORMAT = (".m4a", "ipod", "aac")


def is_audio_only(media_path: str) -> bool:
    """映像トラックを持たないファイルかどうかを判定する。

    まず拡張子で判断し、動画の拡張子でも映像が入っていない場合があるので
    その場合だけ実際に開いて確かめる。
    """
    if os.path.splitext(media_path)[1].lower() in AUDIO_EXTENSIONS:
        return True

    from moviepy import VideoFileClip

    try:
        with VideoFileClip(media_path):
            return False
    except Exception:
        return True


# --------------------------------------------------------------------------
# moviepy 1.x / 2.x 互換ヘルパー
# --------------------------------------------------------------------------

def _subclip(clip, start: float, end: float):
    if hasattr(clip, "subclipped"):      # moviepy 2.x
        return clip.subclipped(start, end)
    return clip.subclip(start, end)      # moviepy 1.x


def _with_audio(clip, audio):
    if hasattr(clip, "with_audio"):      # moviepy 2.x
        return clip.with_audio(audio)
    return clip.set_audio(audio)         # moviepy 1.x


# --------------------------------------------------------------------------
# 音声抽出
# --------------------------------------------------------------------------

def extract_audio(media_path: str, output_wav: str, fps: int = 44100) -> str:
    """動画・音声のどちらからでも wav を抽出する。

    moviepy を通すと音声のみのファイルで失敗するため、ffmpeg を直接呼ぶ。
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_wav)), exist_ok=True)

    result = subprocess.run(
        [
            ffmpeg_tools.ffmpeg_exe(), "-y", "-loglevel", "error",
            "-i", media_path,
            "-vn",                    # 映像は捨てる
            "-acodec", "pcm_s16le",
            "-ar", str(fps),
            output_wav,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not os.path.exists(output_wav):
        raise FileNotFoundError(
            f"音声を抽出できませんでした（音声トラックが無い可能性があります）: "
            f"{os.path.basename(media_path)}\n{result.stderr.strip()[:300]}"
        )
    return output_wav


def get_duration(media_path: str) -> float:
    """動画・音声の総再生時間を秒で返す。"""
    if is_audio_only(media_path):
        from moviepy import AudioFileClip

        with AudioFileClip(media_path) as clip:
            return float(clip.duration)

    from moviepy import VideoFileClip

    with VideoFileClip(media_path) as clip:
        return float(clip.duration)


# --------------------------------------------------------------------------
# メイン処理
# --------------------------------------------------------------------------

def process_video(
    video_path: str,
    keep_segments: Sequence[Segment],
    output_path: str,
    pitch_shift_semitones: float = 0.0,
    formant_ratio: float = 1.0,
    pitch_method: str = "librosa",
    converted_audio_path: str | None = None,
    work_dir: str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    **write_kwargs,
) -> str:
    """Keep List に従って映像をカットし、声色変換した音声と合わせて書き出す。

    Args:
        video_path: 入力動画
        keep_segments: 残す区間 [(start, end), ...]
        output_path: 出力 mp4 パス
        pitch_shift_semitones: ピッチ変化量（半音）。0 なら変換しない
        pitch_method: "librosa"（話速維持）/ "pydub"（簡易）
        converted_audio_path: 変換済み音声を既に持っている場合に指定（再変換を省く）
        work_dir: 中間ファイル置き場。None なら一時ディレクトリ
        progress_callback: (0.0-1.0, メッセージ) を受け取るコールバック
        **write_kwargs: write_videofile へそのまま渡す追加引数

    Returns:
        output_path
    """
    from moviepy import AudioFileClip, VideoFileClip, concatenate_videoclips

    if not keep_segments:
        raise ValueError("残す区間がありません。無音の閾値を緩めてください。")

    def report(ratio: float, message: str) -> None:
        if progress_callback:
            progress_callback(ratio, message)

    temp_dir_obj = None
    if work_dir is None:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="autocutter_")
        work_dir = temp_dir_obj.name
    os.makedirs(work_dir, exist_ok=True)

    opened = []
    try:
        report(0.05, "動画を読み込み中...")
        clip = VideoFileClip(video_path)
        opened.append(clip)

        # --- 声色変換 -----------------------------------------------------
        audio_clip = None
        if converted_audio_path is None and (pitch_shift_semitones or formant_ratio != 1.0):
            report(0.15, "音声を抽出中...")
            src_wav = os.path.join(work_dir, "source_audio.wav")
            extract_audio(video_path, src_wav)

            report(0.30, "声色を変換中...")
            converted_audio_path = voice_changer.convert_voice_file(
                src_wav,
                os.path.join(work_dir, "converted_audio.wav"),
                semitones=pitch_shift_semitones,
                formant_ratio=formant_ratio,
                method=pitch_method,
            )

        if converted_audio_path:
            audio_clip = AudioFileClip(converted_audio_path)
            opened.append(audio_clip)

            # pydub 方式はピッチと同時に長さも変わるため、映像とズレていないか確認する
            drift = abs(audio_clip.duration - clip.duration)
            if drift > 0.2:
                raise ValueError(
                    f"変換後の音声長が映像と {drift:.2f} 秒ずれています。"
                    "pitch_method='librosa' を使うか、ピッチ変化量を小さくしてください。"
                )
            clip = _with_audio(clip, audio_clip)

        # --- カット & 結合 -------------------------------------------------
        report(0.45, "カット区間を切り出し中...")
        duration = float(clip.duration)
        pieces = []
        for start, end in keep_segments:
            start = max(0.0, min(start, duration))
            end = max(0.0, min(end, duration))
            if end - start > 0.01:
                pieces.append(_subclip(clip, start, end))

        if not pieces:
            raise ValueError("切り出せる区間がありませんでした。")

        final = concatenate_videoclips(pieces) if len(pieces) > 1 else pieces[0]
        opened.append(final)

        report(0.60, "エンコード中...（動画の長さによっては数分かかります）")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        params = {
            "codec": "libx264",
            "audio_codec": "aac",
            "temp_audiofile": os.path.join(work_dir, "temp_audio.m4a"),
            "remove_temp": True,
            "logger": None,
        }
        params.update(write_kwargs)
        final.write_videofile(output_path, **params)

        report(1.0, "完了")
        return output_path

    finally:
        for obj in reversed(opened):
            try:
                obj.close()
            except Exception:
                pass
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()


# --------------------------------------------------------------------------
# 音声のみの入力に対する処理
# --------------------------------------------------------------------------

def process_audio(
    media_path: str,
    keep_segments: Sequence[Segment],
    output_path: str,
    pitch_shift_semitones: float = 0.0,
    formant_ratio: float = 1.0,
    pitch_method: str = "librosa",
    converted_audio_path: str | None = None,
    work_dir: str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    bitrate: str = "192k",
) -> str:
    """音声のみの素材を Keep List に従ってカットし、声色変換して書き出す。

    映像が無いので moviepy を通さず pydub だけで完結させる。
    出力形式は output_path の拡張子から決まる（.m4a / .mp3 / .wav など）。
    """
    from pydub import AudioSegment

    # pydub は PATH 上の ffmpeg を探すので、moviepy と同じバイナリを使わせる
    ffmpeg_tools.configure_pydub()

    if not keep_segments:
        raise ValueError("残す区間がありません。無音の閾値を緩めてください。")

    def report(ratio: float, message: str) -> None:
        if progress_callback:
            progress_callback(ratio, message)

    temp_dir_obj = None
    if work_dir is None:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="autocutter_")
        work_dir = temp_dir_obj.name
    os.makedirs(work_dir, exist_ok=True)

    try:
        # --- 元音声を wav に揃える -----------------------------------------
        source_wav = converted_audio_path or os.path.join(work_dir, "source_audio.wav")
        if converted_audio_path is None:
            report(0.10, "音声を読み込み中...")
            if not os.path.exists(source_wav):
                extract_audio(media_path, source_wav)

            # --- 声色変換 --------------------------------------------------
            if pitch_shift_semitones or formant_ratio != 1.0:
                report(0.30, "声色を変換中...")
                source_wav = voice_changer.convert_voice_file(
                    source_wav,
                    os.path.join(work_dir, "converted_audio.wav"),
                    semitones=pitch_shift_semitones,
                    formant_ratio=formant_ratio,
                    method=pitch_method,
                )

        # --- カット & 結合 -------------------------------------------------
        report(0.55, "カット区間を切り出し中...")
        audio = AudioSegment.from_file(source_wav)
        duration = len(audio) / 1000.0

        result = AudioSegment.empty()
        for start, end in keep_segments:
            start = max(0.0, min(start, duration))
            end = max(0.0, min(end, duration))
            if end - start > 0.01:
                result += audio[int(start * 1000):int(end * 1000)]

        if len(result) == 0:
            raise ValueError("切り出せる区間がありませんでした。")

        # --- 書き出し ------------------------------------------------------
        report(0.80, "書き出し中...")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        ext = os.path.splitext(output_path)[1].lower()
        output_path = _export_audio(result, output_path, ext, bitrate)

        report(1.0, "完了")
        return output_path

    finally:
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()


def supported_output_extension(input_path: str) -> str:
    """入力に合わせた出力拡張子を返す。未対応の形式は m4a に寄せる。"""
    ext = os.path.splitext(input_path)[1].lower()
    return ext if ext in _EXPORT_FORMATS else ".m4a"


def _export_audio(segment, output_path: str, ext: str, bitrate: str) -> str:
    """候補の (format, codec) を順に試して書き出す。

    どれも駄目なら m4a に切り替えて書き出し、実際に出力したパスを返す。
    """
    candidates = list(_EXPORT_FORMATS.get(ext, _EXPORT_FORMATS[".m4a"]))
    fallback_ext, fallback_fmt, fallback_codec = _FALLBACK_FORMAT
    if ext != fallback_ext:
        candidates.append((fallback_fmt, fallback_codec))

    last_error: Exception | None = None
    for index, (fmt, codec) in enumerate(candidates):
        # 最後の候補は拡張子ごと m4a に切り替える
        is_fallback = index == len(candidates) - 1 and ext != fallback_ext
        path = (
            os.path.splitext(output_path)[0] + fallback_ext if is_fallback else output_path
        )

        params = {"format": fmt}
        if codec:
            params["codec"] = codec
        if fmt != "wav":
            params["bitrate"] = bitrate

        try:
            segment.export(path, **params)
            return path
        except Exception as e:  # エンコーダが無いビルドでは次の候補へ
            last_error = e

    raise RuntimeError(f"音声の書き出しに失敗しました: {last_error}")
