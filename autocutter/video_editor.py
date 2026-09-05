"""
video_editor.py — 編集・出力モジュール

「残す区間（Keep List）」に従って映像を切り出し、声色変換した音声と合成して
最終的な mp4 を書き出す。moviepy 1.x / 2.x の API 差は薄いラッパーで吸収する。
"""

from __future__ import annotations

import os
import tempfile
from typing import Callable, Sequence

from . import voice_changer

Segment = tuple[float, float]


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

def extract_audio(video_path: str, output_wav: str, fps: int = 44100) -> str:
    """動画から wav を抽出する。音声トラックが無ければ FileNotFoundError。"""
    from moviepy import VideoFileClip

    os.makedirs(os.path.dirname(os.path.abspath(output_wav)), exist_ok=True)
    with VideoFileClip(video_path) as clip:
        if clip.audio is None:
            raise FileNotFoundError(f"音声トラックが見つかりません: {video_path}")
        clip.audio.write_audiofile(output_wav, fps=fps, logger=None)
    return output_wav


def get_duration(video_path: str) -> float:
    """動画（または音声）の総再生時間を秒で返す。"""
    from moviepy import VideoFileClip

    with VideoFileClip(video_path) as clip:
        return float(clip.duration)


# --------------------------------------------------------------------------
# メイン処理
# --------------------------------------------------------------------------

def process_video(
    video_path: str,
    keep_segments: Sequence[Segment],
    output_path: str,
    pitch_shift_semitones: float = 0.0,
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
        if converted_audio_path is None and pitch_shift_semitones:
            report(0.15, "音声を抽出中...")
            src_wav = os.path.join(work_dir, "source_audio.wav")
            extract_audio(video_path, src_wav)

            report(0.30, "声色を変換中...")
            converted_audio_path = voice_changer.shift_pitch_file(
                src_wav,
                os.path.join(work_dir, "converted_audio.wav"),
                pitch_shift_semitones,
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
