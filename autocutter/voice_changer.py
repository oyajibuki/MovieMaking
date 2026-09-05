"""
voice_changer.py — 音声変換モジュール

身バレ防止のためのピッチシフト（声色変換）を行う。

2 方式を用意している:
  - "librosa": 話速を保ったままピッチだけ変える（品質重視・既定）
  - "pydub"  : リサンプリングによる簡易変換。話速も変わるが依存が軽く高速
"""

from __future__ import annotations

import os

# 実用上、これ以上動かすとケロケロ声になり聞き取れなくなる
MAX_SEMITONES = 12.0


def semitones_to_octaves(semitones: float) -> float:
    """半音 → オクターブ。"""
    return semitones / 12.0


def shift_pitch(audio_segment, octaves: float):
    """pydub の AudioSegment のピッチをオクターブ単位で変更する。

    サンプリングレートを書き換えて元のレートに戻す古典的な手法。
    ピッチと同時に再生速度も変わる点に注意（テープの早回しと同じ原理）。

    Args:
        audio_segment: pydub.AudioSegment
        octaves: 変化量。+0.25 で少し高く、-0.25 で少し低くなる

    Returns:
        pydub.AudioSegment
    """
    if octaves == 0:
        return audio_segment

    new_sample_rate = int(audio_segment.frame_rate * (2.0 ** octaves))
    shifted = audio_segment._spawn(
        audio_segment.raw_data, overrides={"frame_rate": new_sample_rate}
    )
    return shifted.set_frame_rate(audio_segment.frame_rate)


def shift_pitch_file(
    input_path: str,
    output_path: str,
    semitones: float,
    method: str = "librosa",
) -> str:
    """音声ファイルにピッチシフトを掛けて別ファイルへ書き出す。

    Args:
        input_path: 入力音声。librosa 方式は soundfile が読める形式（wav/flac 等）のみ。
                    mp4 等を渡した場合は自動的に pydub 方式へフォールバックする
        output_path: 出力 wav パス
        semitones: 半音単位の変化量（+ で高く、- で低く）
        method: "librosa"（話速維持）または "pydub"（簡易・高速）

    Returns:
        output_path
    """
    semitones = max(-MAX_SEMITONES, min(MAX_SEMITONES, float(semitones)))

    if semitones == 0:
        # 変換不要。呼び出し側の分岐を減らすため入力をそのまま返す
        return input_path

    if method == "librosa":
        try:
            return _shift_with_librosa(input_path, output_path, semitones)
        except ImportError:
            # librosa/soundfile 未導入の環境では簡易方式へフォールバック
            method = "pydub"
        except Exception as e:
            # librosa 1.0 以降は soundfile が読める形式（wav/flac 等）しか扱えない。
            # mp4 等を直接渡された場合は ffmpeg 経由の pydub 方式へ回す。
            if "Format not recognised" not in str(e):
                raise
            method = "pydub"

    return _shift_with_pydub(input_path, output_path, semitones)


def _shift_with_librosa(input_path: str, output_path: str, semitones: float) -> str:
    import warnings

    import librosa
    import soundfile as sf

    y, sr = librosa.load(input_path, sr=None, mono=False)

    # librosa 1.0 の内部実装が出す FutureWarning / numba の cast 警告は実害が無いので抑制
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if y.ndim == 1:
            data = librosa.effects.pitch_shift(y=y, sr=sr, n_steps=semitones)
        else:
            # チャンネルごとに処理して (samples, channels) 形式へ戻す
            channels = [
                librosa.effects.pitch_shift(y=ch, sr=sr, n_steps=semitones) for ch in y
            ]
            data = list(zip(*channels))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sf.write(output_path, data, sr)
    return output_path


def _shift_with_pydub(input_path: str, output_path: str, semitones: float) -> str:
    from pydub import AudioSegment

    audio = AudioSegment.from_file(input_path)
    shifted = shift_pitch(audio, semitones_to_octaves(semitones))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    shifted.export(output_path, format="wav")
    return output_path
