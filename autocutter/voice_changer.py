"""
voice_changer.py — 声色変換モジュール

身バレ防止のために声の高さと声質を変える。

声の性別・年齢の印象を決めているのはピッチだけではなく **フォルマント**
（声道の共鳴。体格に対応する）で、ピッチだけ動かすと早回しのような
不自然な声になる。そこで 2 つを独立に操作する。

  - ピッチ（半音）    : 声の高さ
  - フォルマント倍率  : 1 より大きいと細い / 若い声、小さいと太い / 大人びた声

処理方式:
  - "librosa": 話速を保ったままピッチを変え、フォルマントを別途ワープする（既定）
  - "pydub"  : リサンプリングによる簡易変換。話速も変わるが依存が軽く高速
"""

from __future__ import annotations

import os

# 低い声から女性・子供の音域へ上げるには大きな変化量が要る
MAX_SEMITONES = 20.0

# フォルマント倍率の実用範囲
MIN_FORMANT = 0.70
MAX_FORMANT = 1.45

# 声色プリセット
#   target_f0 : 目指す声の高さ（Hz）。話者の実際の高さから必要な半音数を計算する
#   formant   : フォルマント倍率
#   fallback  : F0 を測れなかったときに使う固定の半音数
#
# 相対的な半音数で指定すると、元の声の高さによって着地点がまるで変わってしまう。
# 例えば F0 が 74Hz の低い声では +5 半音でも 101Hz にしかならず、
# 女性の音域（約 200Hz）には全く届かない。そのため目標値で指定する。
VOICE_PRESETS: dict[str, dict] = {
    "そのまま（変換しない）": {
        "target_f0": None, "formant": 1.00, "fallback": 0.0, "direction": None},
    "女性の声": {
        "target_f0": 200.0, "formant": 1.18, "fallback": 6.0, "direction": "up"},
    "高めの女性の声": {
        "target_f0": 240.0, "formant": 1.26, "fallback": 8.0, "direction": "up"},
    "子供の声": {
        "target_f0": 290.0, "formant": 1.38, "fallback": 10.0, "direction": "up"},
    "太い男の声": {
        "target_f0": 85.0, "formant": 0.84, "fallback": -4.0, "direction": "down"},
    "低い男の声": {
        "target_f0": 100.0, "formant": 0.90, "fallback": -2.5, "direction": "down"},
    "年配の男性の声": {
        "target_f0": 110.0, "formant": 0.95, "fallback": -3.0, "direction": "down"},
    "軽い匿名化（自然さ優先）": {
        "target_f0": None, "formant": 1.07, "fallback": 2.0, "direction": None},
}

DEFAULT_PRESET = "そのまま（変換しない）"

# F0 推定に使う範囲（極端に低い声・高い声も拾えるようにする）
F0_MIN = 50.0
F0_MAX = 600.0


def estimate_f0(audio_path: str) -> float | None:
    """話者の基本周波数（声の高さ）の中央値を Hz で返す。

    有声フレームが取れないときは None。
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        if len(y) < sr // 4:
            return None

        f0, _voiced, _prob = librosa.pyin(y, fmin=F0_MIN, fmax=F0_MAX, sr=sr)
        f0 = f0[~np.isnan(f0)]
        if len(f0) == 0:
            return None
        return float(np.median(f0))
    except Exception:
        return None


def resolve_preset(
    name: str, strength: float = 1.0, source_f0: float | None = None
) -> tuple[float, float]:
    """プリセット名から (ピッチ半音, フォルマント倍率) を返す。

    source_f0（話者の実際の声の高さ）が分かっていれば、目標の高さに
    届くだけの半音数を計算する。分からなければ固定値にフォールバックする。

    strength は変化量の倍率。1.0 が既定で、0 にすると無変換になる。
    """
    import math

    preset = VOICE_PRESETS.get(name, VOICE_PRESETS[DEFAULT_PRESET])

    target = preset["target_f0"]
    fallback = preset["fallback"]
    direction = preset.get("direction")

    if target and source_f0 and source_f0 > 0:
        semitones = 12.0 * math.log2(target / source_f0)
        # 既に目標より低い声に「太い男の声」を掛けると逆に高くなってしまう。
        # 意図した向きと逆になる場合は固定値に戻して、さらに深く／高くする。
        if direction == "down" and semitones > 0:
            semitones = fallback
        elif direction == "up" and semitones < 0:
            semitones = fallback
    else:
        semitones = fallback

    semitones *= strength
    # フォルマントは 1.0 を中心に増減するので、1.0 からの差分に強さを掛ける
    formant = 1.0 + (preset["formant"] - 1.0) * strength

    semitones = max(-MAX_SEMITONES, min(MAX_SEMITONES, semitones))
    formant = max(MIN_FORMANT, min(MAX_FORMANT, formant))
    return semitones, formant


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


def warp_formants(y, sr: int, ratio: float, n_fft: int = 2048, hop_length: int = 512,
                  lifter: int = 30):
    """スペクトル包絡（フォルマント）だけを周波数方向に ratio 倍する。

    ピッチ（倍音の位置）は動かさず、共鳴のピーク位置だけをずらすので、
    声の高さを変えずに「体格」の印象を変えられる。

    ケプストラム法で包絡を取り出し、周波数軸を伸縮させた包絡との比を
    元のスペクトルに掛けている。

    Args:
        y: モノラルの波形
        sr: サンプリングレート
        ratio: 1 より大きいと細い / 若い声、小さいと太い声
        lifter: ケプストラムのどこまでを包絡とみなすか（大きいほど細かい形を拾う）
    """
    import librosa
    import numpy as np

    if ratio == 1.0 or len(y) < n_fft:
        return y

    spectrum = librosa.stft(y, n_fft=n_fft, hop_length=hop_length)
    magnitude = np.abs(spectrum)
    phase = np.angle(spectrum)

    n_bins = magnitude.shape[0]
    log_magnitude = np.log(magnitude + 1e-10)

    # --- ケプストラムの低ケフレンシー成分＝スペクトル包絡 ---
    cepstrum = np.fft.irfft(log_magnitude, n=2 * (n_bins - 1), axis=0)
    cepstrum[lifter:-lifter] = 0.0
    envelope_log = np.fft.rfft(cepstrum, n=2 * (n_bins - 1), axis=0).real

    # --- 包絡を周波数方向に伸縮する ---
    bins = np.arange(n_bins)
    source_bins = np.clip(bins / ratio, 0, n_bins - 1)
    warped_log = np.empty_like(envelope_log)
    for frame in range(envelope_log.shape[1]):
        warped_log[:, frame] = np.interp(source_bins, bins, envelope_log[:, frame])

    # --- 元の包絡を打ち消して、伸縮した包絡を掛け直す ---
    gain = np.exp(np.clip(warped_log - envelope_log, -6.0, 6.0))
    adjusted = magnitude * gain

    result = librosa.istft(
        adjusted * np.exp(1j * phase), hop_length=hop_length, length=len(y)
    )
    return result.astype(y.dtype, copy=False)


def convert_voice_file(
    input_path: str,
    output_path: str,
    semitones: float = 0.0,
    formant_ratio: float = 1.0,
    method: str = "librosa",
) -> str:
    """ピッチとフォルマントを指定して声色を変える。

    librosa のピッチシフトはフォルマントも一緒に動かしてしまうため、
    目標のフォルマント倍率になるよう差分だけを打ち消すワープを掛ける。

    Args:
        input_path: 入力音声（librosa 方式は wav 等 soundfile が読める形式）
        output_path: 出力 wav パス
        semitones: ピッチ変化量（半音）
        formant_ratio: フォルマント倍率（1.0 で変えない）
        method: "librosa"（話速維持・フォルマント対応）/ "pydub"（簡易）

    Returns:
        実際に書き出したパス。無変換のときは input_path をそのまま返す
    """
    semitones = max(-MAX_SEMITONES, min(MAX_SEMITONES, float(semitones)))
    formant_ratio = max(MIN_FORMANT, min(MAX_FORMANT, float(formant_ratio)))

    if semitones == 0 and formant_ratio == 1.0:
        # 変換不要。呼び出し側の分岐を減らすため入力をそのまま返す
        return input_path

    if method == "librosa":
        try:
            return _convert_with_librosa(
                input_path, output_path, semitones, formant_ratio
            )
        except ImportError:
            method = "pydub"
        except Exception as e:
            if "Format not recognised" not in str(e):
                raise
            method = "pydub"

    # pydub 方式はフォルマントを独立に扱えないのでピッチのみ
    return _shift_with_pydub(input_path, output_path, semitones)


def _convert_with_librosa(
    input_path: str, output_path: str, semitones: float, formant_ratio: float
) -> str:
    import warnings

    import librosa
    import numpy as np
    import soundfile as sf

    y, sr = librosa.load(input_path, sr=None, mono=False)

    # ピッチシフトはフォルマントも同じ倍率で動かすので、その分を差し引く
    pitch_ratio = 2.0 ** (semitones / 12.0)
    residual_ratio = formant_ratio / pitch_ratio if semitones else formant_ratio

    def convert(channel):
        if semitones:
            channel = librosa.effects.pitch_shift(
                y=channel, sr=sr, n_steps=semitones
            )
        if abs(residual_ratio - 1.0) > 1e-3:
            channel = warp_formants(channel, sr, residual_ratio)
        return channel

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if y.ndim == 1:
            data = convert(y)
        else:
            data = list(zip(*[convert(ch) for ch in y]))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sf.write(output_path, data, sr)
    return output_path


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

    from . import ffmpeg_tools

    ffmpeg_tools.configure_pydub()
    audio = AudioSegment.from_file(input_path)
    shifted = shift_pitch(audio, semitones_to_octaves(semitones))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    shifted.export(output_path, format="wav")
    return output_path


def describe_preset(
    name: str, strength: float = 1.0, source_f0: float | None = None
) -> dict:
    """プリセットを適用したときに何が起きるかを説明用にまとめる。

    変化量が大きすぎて上限で頭打ちになった場合は reached_f0 が target_f0 に
    届かない。UI 側でその旨を伝えるために使う。
    """
    semitones, formant = resolve_preset(name, strength, source_f0)
    preset = VOICE_PRESETS.get(name, VOICE_PRESETS[DEFAULT_PRESET])
    target = preset["target_f0"]

    reached = source_f0 * (2.0 ** (semitones / 12.0)) if source_f0 else None
    clamped = bool(
        target and reached and abs(reached - target) > target * 0.05
    )

    return {
        "semitones": semitones,
        "formant": formant,
        "source_f0": source_f0,
        "target_f0": target,
        "reached_f0": reached,
        "clamped": clamped,
    }
