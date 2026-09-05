"""
audio_analyzer.py — 解析モジュール

無音区間・フィラーワード区間を検出し、「残す区間（Keep List）」を算出する。
このモジュールは pydub 以外に重い依存を持たず、区間演算部分は純粋な Python で完結する。
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence

# 区間は (start_sec, end_sec) のタプルで統一する
Segment = tuple[float, float]

# 日本語のフィラー（言い淀み）既定リスト
DEFAULT_FILLER_WORDS_JA = [
    "えー", "えーと", "えっと", "えと", "あー", "あのー", "あの",
    "そのー", "まあ", "まー", "なんか", "うーん", "んー", "ええと",
]

# 英語のフィラー既定リスト
DEFAULT_FILLER_WORDS_EN = [
    "um", "uh", "erm", "ah", "er", "hmm", "like", "you know", "i mean",
]

# Whisper の出力に混ざる記号類（比較時に落とす）
_PUNCT_RE = re.compile(r"[\s、。，．,\.！？!\?「」『』…・\-—:;\"'（）\(\)]+")


def _normalize(text: str) -> str:
    """比較用にテキストを正規化する（記号除去・小文字化・長音統一）。"""
    text = _PUNCT_RE.sub("", text)
    text = text.replace("〜", "ー").replace("~", "ー")
    return text.lower()


# --------------------------------------------------------------------------
# 無音検知
# --------------------------------------------------------------------------

def resolve_threshold(audio, threshold_db: float, relative_offset_db: float | None) -> float:
    """実際に使う無音の閾値（dBFS）を決める。

    relative_offset_db が指定されていれば、素材の平均音量から
    その分だけ下を閾値にする。小さく録れた音声でも喋っている部分を
    無音と誤判定しないようにするための調整。
    """
    if relative_offset_db is None:
        return threshold_db

    average = audio.dBFS
    if average == float("-inf"):  # 完全な無音
        return threshold_db
    return average - relative_offset_db


def detect_silence(
    audio_path: str,
    threshold_db: float = -38.0,
    min_silence_len: float = 0.5,
    seek_step: int = 10,
    relative_offset_db: float | None = None,
) -> list[Segment]:
    """音量が閾値以下の状態が min_silence_len 秒以上続く区間を返す。

    Args:
        audio_path: wav 等の音声ファイルパス
        threshold_db: 無音とみなす閾値（dBFS）。relative_offset_db 未指定時に使う
        min_silence_len: 無音とみなす最短の長さ（秒）
        seek_step: 走査ステップ（ms）。小さいほど精密だが遅い
        relative_offset_db: 指定すると「素材の平均音量 - この値」を閾値にする。
            静かに録れた素材で喋りごと切ってしまう事故を防げる（16 前後が目安）

    Returns:
        [(start_sec, end_sec), ...] 昇順
    """
    from pydub import AudioSegment
    from pydub.silence import detect_silence as _pydub_detect_silence

    from . import ffmpeg_tools

    ffmpeg_tools.configure_pydub()
    audio = AudioSegment.from_file(audio_path)
    threshold = resolve_threshold(audio, threshold_db, relative_offset_db)

    ranges_ms = _pydub_detect_silence(
        audio,
        min_silence_len=int(min_silence_len * 1000),
        silence_thresh=threshold,
        seek_step=seek_step,
    )
    return [(start / 1000.0, end / 1000.0) for start, end in ranges_ms]


def measure_loudness(audio_path: str) -> float:
    """素材の平均音量（dBFS）を返す。UI に実効閾値を表示するために使う。"""
    from pydub import AudioSegment

    from . import ffmpeg_tools

    ffmpeg_tools.configure_pydub()
    return AudioSegment.from_file(audio_path).dBFS


# --------------------------------------------------------------------------
# フィラー検知（既存 Whisper アプリの出力をそのまま食わせる）
# --------------------------------------------------------------------------

def detect_fillers(
    whisper_result: dict | Sequence[dict],
    filler_words: Iterable[str] | None = None,
    padding: float = 0.02,
) -> list[Segment]:
    """Whisper の認識結果からフィラーワードの区間を返す。

    Whisper の日本語の単語タイムスタンプは "えーと" が 'え' 'ー' 'と' のように
    1 文字ずつに割れることが多い。そのため単語 1 つずつではなく、
    連続する単語をつなげた文字列と照合する（最長一致を優先）。

    単語タイムスタンプが無い場合は、セグメント全体がフィラーのみで構成される
    ケースに限り検出する（誤カットを避けるため保守的に判定）。

    Args:
        whisper_result: transcribe() の戻り値、または segments のリスト
        filler_words: カット対象の語のリスト（None なら日英の既定リスト）
        padding: 検出区間の前後に足す余白（秒）

    Returns:
        [(start_sec, end_sec), ...]
    """
    if filler_words is None:
        filler_words = DEFAULT_FILLER_WORDS_JA + DEFAULT_FILLER_WORDS_EN

    targets = {_normalize(w) for w in filler_words if _normalize(w)}
    if not targets:
        return []

    max_len = max(len(t) for t in targets)
    segments = whisper_result["segments"] if isinstance(whisper_result, dict) else whisper_result

    cuts: list[Segment] = []
    for seg in segments:
        words = seg.get("words") or []
        if words:
            cuts.extend(_match_filler_runs(words, targets, max_len, padding))
        else:
            # 単語タイムスタンプが無い場合、セグメント全体がフィラーのときのみカット
            if _normalize(seg.get("text", "")) in targets:
                start = float(seg["start"]) - padding
                end = float(seg["end"]) + padding
                cuts.append((max(0.0, start), end))

    return merge_segments(cuts)


def _match_filler_runs(
    words: Sequence[dict],
    targets: set[str],
    max_len: int,
    padding: float,
) -> list[Segment]:
    """連続する単語をつなげてフィラーと照合する（最長一致・非重複）。"""
    normalized = [_normalize(w.get("word", "")) for w in words]

    cuts: list[Segment] = []
    i = 0
    while i < len(words):
        best_end = None  # 一致した範囲の終端インデックス（排他）
        joined = ""

        for j in range(i, len(words)):
            joined += normalized[j]
            if len(joined) > max_len:
                break
            if joined in targets:
                best_end = j + 1  # より長い一致があれば上書きされる

        if best_end is None:
            i += 1
            continue

        start = float(words[i]["start"]) - padding
        end = float(words[best_end - 1]["end"]) + padding
        cuts.append((max(0.0, start), end))
        i = best_end  # 一致した範囲は飛ばす

    return cuts


# --------------------------------------------------------------------------
# 区間演算
# --------------------------------------------------------------------------

def merge_segments(segments: Iterable[Segment], gap: float = 0.0) -> list[Segment]:
    """重なった／gap 秒以内で隣接する区間をマージし、昇順に整列して返す。"""
    ordered = sorted((float(s), float(e)) for s, e in segments if e > s)
    if not ordered:
        return []

    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def apply_margin(cut_segments: Iterable[Segment], margin: float) -> list[Segment]:
    """カット区間の前後に margin 秒の余白を残す（＝カット区間を内側に縮める）。

    ブツ切り感を防ぐための処理。縮めた結果 0 以下になった区間は破棄する。
    """
    if margin <= 0:
        return merge_segments(cut_segments)

    shrunk = []
    for start, end in cut_segments:
        new_start = start + margin
        new_end = end - margin
        if new_end > new_start:
            shrunk.append((new_start, new_end))
    return merge_segments(shrunk)


def generate_keep_segments(
    total_duration: float,
    cut_segments: Iterable[Segment],
    min_keep_len: float = 0.05,
) -> list[Segment]:
    """全長からカット区間を差し引き、「残す区間」のリストを作る。

    Args:
        total_duration: 元動画の総再生時間（秒）
        cut_segments: カットする区間
        min_keep_len: これより短い残存区間は破棄する（エンコード事故防止）

    Returns:
        [(start_sec, end_sec), ...]
    """
    cuts = merge_segments(cut_segments)
    keeps: list[Segment] = []
    cursor = 0.0

    for start, end in cuts:
        start = max(0.0, min(start, total_duration))
        end = max(0.0, min(end, total_duration))
        if start > cursor:
            keeps.append((cursor, start))
        cursor = max(cursor, end)

    if cursor < total_duration:
        keeps.append((cursor, total_duration))

    return [(s, e) for s, e in keeps if e - s >= min_keep_len]


def total_length(segments: Iterable[Segment]) -> float:
    """区間リストの合計長（秒）。"""
    return sum(e - s for s, e in segments)


# --------------------------------------------------------------------------
# タイムライン再マッピング（カット後の字幕ズレ補正）
# --------------------------------------------------------------------------

def build_time_mapper(keep_segments: Sequence[Segment]) -> Callable[[float], float | None]:
    """元動画の時刻 → 編集後動画の時刻 に変換する関数を返す。

    カットされた時刻を渡した場合は None を返す。
    """
    offsets: list[tuple[float, float, float]] = []  # (start, end, new_start)
    elapsed = 0.0
    for start, end in keep_segments:
        offsets.append((start, end, elapsed))
        elapsed += end - start

    def mapper(t: float) -> float | None:
        for start, end, new_start in offsets:
            if start <= t <= end:
                return new_start + (t - start)
        return None

    return mapper


def remap_subtitles(
    segments: Sequence[dict],
    keep_segments: Sequence[Segment],
    min_duration: float = 0.15,
) -> list[dict]:
    """字幕セグメントを編集後のタイムラインに合わせて貼り直す。

    カットにまたがる字幕は、残存部分だけを取り出して分割せずに連結する
    （テキストは維持し、開始・終了だけを詰める）。完全に消えた字幕は落とす。
    """
    mapper = build_time_mapper(keep_segments)
    result: list[dict] = []

    for seg in segments:
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])

        # 字幕区間と残存区間の重なりを取り、編集後時刻に変換する
        pieces = []
        for k_start, k_end in keep_segments:
            overlap_start = max(seg_start, k_start)
            overlap_end = min(seg_end, k_end)
            if overlap_end > overlap_start:
                pieces.append((mapper(overlap_start), mapper(overlap_end)))

        if not pieces:
            continue

        new_start = pieces[0][0]
        new_end = pieces[-1][1]
        if new_end - new_start < min_duration:
            new_end = new_start + min_duration

        new_seg = dict(seg)
        new_seg["start"] = new_start
        new_seg["end"] = new_end
        result.append(new_seg)

    # 直前の字幕と重ならないように終端を調整
    for i in range(len(result) - 1):
        if result[i]["end"] > result[i + 1]["start"]:
            result[i]["end"] = max(result[i]["start"], result[i + 1]["start"] - 0.01)

    return result
