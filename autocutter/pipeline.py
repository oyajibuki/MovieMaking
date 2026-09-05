"""
pipeline.py — 設計書 4章のデータ処理フローをそのまま関数化したもの

  Input → 音声分離 → 音声認識 → カット区間算出 → 声色変換 → 動画結合 → Output
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from . import audio_analyzer, subtitle_utils, transcriber, video_editor, voice_changer

Segment = tuple[float, float]


@dataclass
class CutSettings:
    """UI から渡ってくる処理設定。"""

    # 無音カット
    remove_silence: bool = True
    silence_threshold_db: float = -38.0
    min_silence_len: float = 0.5
    # True なら「素材の平均音量 - silence_relative_offset_db」を閾値にする。
    # 小さく録れた音声を喋りごと切ってしまう事故を防げるので既定で有効。
    silence_auto_threshold: bool = True
    silence_relative_offset_db: float = 16.0

    # フィラーカット
    remove_fillers: bool = True
    filler_words: list[str] = field(
        default_factory=lambda: list(audio_analyzer.DEFAULT_FILLER_WORDS_JA)
    )
    # Whisper は既定だと言い淀みを整形して落とすので、プロンプトで書き起こしを促す
    prompt_for_fillers: bool = True

    # 共通
    margin: float = 0.08          # カット前後に残す余白（秒）
    min_keep_len: float = 0.10    # これより短い残存区間は捨てる

    # 声色変換
    pitch_shift_semitones: float = 0.0
    pitch_method: str = "librosa"

    # 音声認識
    model_size: str = "base"
    language: str = "ja"


@dataclass
class CutResult:
    """処理結果。動画を書き出す前の「解析だけ」の段階でも返せる。"""

    keep_segments: list[Segment]
    silence_cuts: list[Segment]
    filler_cuts: list[Segment]
    original_duration: float
    subtitles: list[dict]
    whisper_result: dict | None = None
    output_video: str | None = None
    is_audio_only: bool = False
    # 実際に使われた無音の閾値と素材の平均音量（UI での説明用）
    effective_threshold_db: float | None = None
    average_loudness_db: float | None = None

    @property
    def new_duration(self) -> float:
        return audio_analyzer.total_length(self.keep_segments)

    @property
    def removed_duration(self) -> float:
        return max(0.0, self.original_duration - self.new_duration)

    @property
    def removed_ratio(self) -> float:
        if self.original_duration <= 0:
            return 0.0
        return self.removed_duration / self.original_duration

    def srt(self) -> str:
        return subtitle_utils.create_srt_content(self.subtitles)

    def ass(self, **style) -> str:
        return subtitle_utils.create_ass_content(self.subtitles, **style)


def analyze(
    media_path: str,
    settings: CutSettings,
    work_dir: str,
    whisper_result: dict | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> CutResult:
    """素材を解析し、カット区間・残す区間・補正済み字幕を算出する（書き出しはしない）。

    media_path は動画でも音声のみ（mp3 / m4a / wav 等）でもよい。
    """

    def report(ratio: float, message: str) -> None:
        if progress_callback:
            progress_callback(ratio, message)

    os.makedirs(work_dir, exist_ok=True)

    # 1. 音声分離
    report(0.05, "音声を抽出中...")
    audio_path = os.path.join(work_dir, "source_audio.wav")
    if not os.path.exists(audio_path):
        video_editor.extract_audio(media_path, audio_path)

    duration = video_editor.get_duration(media_path)
    audio_only = video_editor.is_audio_only(media_path)

    # 2. 音声認識（既存 Whisper の結果を渡せば再解析しない）
    #    フィラー検知だけでなくテロップ出力にも使うため、常に実行する
    if whisper_result is None:
        report(0.15, f"音声認識中...（model={settings.model_size}）")
        prompt = None
        if settings.remove_fillers and settings.prompt_for_fillers:
            prompt = transcriber.build_filler_prompt(
                settings.filler_words, settings.language
            )
        whisper_result = transcriber.transcribe(
            audio_path,
            model_size=settings.model_size,
            language=settings.language,
            word_timestamps=True,
            initial_prompt=prompt or None,
        )

    segments = whisper_result["segments"] if whisper_result else []

    # 3. カット区間の算出（フローA: フィラー / フローB: 無音）
    filler_cuts: list[Segment] = []
    if settings.remove_fillers and segments:
        report(0.60, "フィラーワードを検出中...")
        filler_cuts = audio_analyzer.detect_fillers(segments, settings.filler_words)

    silence_cuts: list[Segment] = []
    average_loudness = audio_analyzer.measure_loudness(audio_path)
    relative_offset = (
        settings.silence_relative_offset_db if settings.silence_auto_threshold else None
    )
    effective_threshold = settings.silence_threshold_db
    if settings.silence_auto_threshold and average_loudness != float("-inf"):
        effective_threshold = average_loudness - settings.silence_relative_offset_db

    if settings.remove_silence:
        report(0.70, "無音区間を検出中...")
        silence_cuts = audio_analyzer.detect_silence(
            audio_path,
            threshold_db=settings.silence_threshold_db,
            min_silence_len=settings.min_silence_len,
            relative_offset_db=relative_offset,
        )

    # 4. マージンを適用してから統合し、残す区間を作る
    report(0.85, "カットリストを作成中...")
    cuts = audio_analyzer.apply_margin(silence_cuts + filler_cuts, settings.margin)
    keep_segments = audio_analyzer.generate_keep_segments(
        duration, cuts, min_keep_len=settings.min_keep_len
    )

    # 5. 字幕をカット後のタイムラインへ貼り直す
    subtitles = audio_analyzer.remap_subtitles(
        subtitle_utils.segments_to_rows(segments), keep_segments
    )

    report(1.0, "解析完了")
    return CutResult(
        keep_segments=keep_segments,
        silence_cuts=silence_cuts,
        filler_cuts=filler_cuts,
        original_duration=duration,
        subtitles=subtitles,
        whisper_result=whisper_result,
        is_audio_only=audio_only,
        effective_threshold_db=effective_threshold,
        average_loudness_db=average_loudness,
    )


def render(
    media_path: str,
    result: CutResult,
    settings: CutSettings,
    output_path: str,
    work_dir: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> str:
    """解析結果に従って動画（または音声）を書き出す。"""
    converted_audio = None
    if settings.pitch_shift_semitones:
        if progress_callback:
            progress_callback(0.1, "声色を変換中...")
        converted_audio = voice_changer.shift_pitch_file(
            os.path.join(work_dir, "source_audio.wav"),
            os.path.join(work_dir, "converted_audio.wav"),
            settings.pitch_shift_semitones,
            method=settings.pitch_method,
        )

    if result.is_audio_only:
        result.output_video = video_editor.process_audio(
            media_path,
            result.keep_segments,
            output_path,
            converted_audio_path=converted_audio,
            work_dir=work_dir,
            progress_callback=progress_callback,
        )
    else:
        result.output_video = video_editor.process_video(
            media_path,
            result.keep_segments,
            output_path,
            converted_audio_path=converted_audio,
            work_dir=work_dir,
            progress_callback=progress_callback,
        )
    return result.output_video


def run(
    media_path: str,
    settings: CutSettings,
    output_path: str,
    work_dir: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> CutResult:
    """解析から書き出しまで一括で実行する。"""
    result = analyze(media_path, settings, work_dir, progress_callback=progress_callback)
    render(media_path, result, settings, output_path, work_dir, progress_callback)
    return result
