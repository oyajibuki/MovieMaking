"""
pipeline.py — 設計書 4章のデータ処理フローをそのまま関数化したもの

  Input → 音声分離 → 音声認識 → カット区間算出 → 声色変換 → 動画結合 → Output
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from . import (
    ai_voice, audio_analyzer, subtitle_utils, transcriber, video_editor, voice_changer
)

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
    # プリセットを使う場合は voice_preset / voice_strength を指定する。
    # 話者の声の高さに応じて必要な半音数が変わるため、解析で F0 を測ってから
    # 書き出し時に解決する（resolve_voice）。
    voice_preset: str = voice_changer.DEFAULT_PRESET
    voice_strength: float = 1.0
    # manual_voice=True のときは下の 2 つをそのまま使う
    manual_voice: bool = False
    pitch_shift_semitones: float = 0.0
    formant_ratio: float = 1.0
    pitch_method: str = "librosa"

    # AI 声質変換（別人の声に置き換える）。指定するとプリセットより優先される。
    # 参照音声のパス、または macOS 組み込み音声の say 名。
    ai_reference_wav: str | None = None
    ai_builtin_voice: str | None = None
    ai_diffusion_steps: int = 25
    # 元の抑揚を追従させる。切ると機械的な喋りになるので既定で有効
    ai_preserve_intonation: bool = True

    @property
    def uses_ai_voice(self) -> bool:
        return bool(self.ai_reference_wav or self.ai_builtin_voice)

    def resolve_voice(self, source_f0: float | None = None) -> tuple[float, float]:
        """(ピッチ半音, フォルマント倍率) を決める。"""
        if self.manual_voice:
            return self.pitch_shift_semitones, self.formant_ratio
        return voice_changer.resolve_preset(
            self.voice_preset, self.voice_strength, source_f0
        )

    def changes_voice(self, source_f0: float | None = None) -> bool:
        semitones, formant = self.resolve_voice(source_f0)
        return bool(semitones) or formant != 1.0

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
    # 話者の声の高さ（Hz）。声色プリセットの変化量を決めるのに使う
    source_f0: float | None = None

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

    # 声の高さを測っておく（声色プリセットが目標の高さに合わせるため）
    source_f0 = voice_changer.estimate_f0(audio_path)

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
        source_f0=source_f0,
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
    source_wav = os.path.join(work_dir, "source_audio.wav")
    converted_audio = None

    # --- AI 声質変換（別人の声）を使う場合はこちらが優先 ---
    if settings.uses_ai_voice:
        if progress_callback:
            progress_callback(0.1, "AI で声を変換中...（実時間程度かかります）")

        reference = settings.ai_reference_wav
        if not reference and settings.ai_builtin_voice:
            reference = ai_voice.build_reference(
                settings.ai_builtin_voice, os.path.join(work_dir, "refs")
            )

        converted_audio = ai_voice.convert(
            source_wav,
            reference,
            os.path.join(work_dir, "converted_audio.wav"),
            diffusion_steps=settings.ai_diffusion_steps,
            preserve_intonation=settings.ai_preserve_intonation,
        )

    semitones, formant = settings.resolve_voice(result.source_f0)
    if converted_audio is None and (semitones or formant != 1.0):
        if progress_callback:
            progress_callback(0.1, "声色を変換中...")
        converted_audio = voice_changer.convert_voice_file(
            source_wav,
            os.path.join(work_dir, "converted_audio.wav"),
            semitones=semitones,
            formant_ratio=formant,
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
