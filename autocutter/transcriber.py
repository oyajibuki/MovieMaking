"""
transcriber.py — 音声認識モジュール

04.subtitle（AI Subtitle）と同じ openai-whisper を使う。
フィラー検知のため word_timestamps=True を既定にしている点だけが差分。
faster-whisper が入っていればそちらを優先し、無ければ openai-whisper を使う。
"""

from __future__ import annotations

MODEL_SIZES = ["tiny", "base", "small", "medium", "large"]

_model_cache: dict[tuple[str, str], object] = {}


def load_model(model_size: str = "base", backend: str = "auto", cache: bool = True):
    """Whisper モデルを読み込む（既定ではプロセス内でキャッシュする）。

    ZeroGPU のように GPU が呼び出しごとに割り当て直される環境では、
    前回の割り当てに紐づいたモデルを使い回せないため cache=False を指定する。
    """
    if backend == "auto":
        backend = "faster" if _has_faster_whisper() else "openai"

    key = (backend, model_size)
    if cache and key in _model_cache:
        return _model_cache[key]

    if backend == "faster":
        from faster_whisper import WhisperModel

        model = WhisperModel(model_size, device="auto", compute_type="int8")
    else:
        import whisper

        model = whisper.load_model(model_size)

    if cache:
        _model_cache[key] = model
    return model


def _has_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe(
    media_path: str,
    model=None,
    model_size: str = "base",
    language: str = "ja",
    word_timestamps: bool = True,
    backend: str = "auto",
    cache_model: bool = True,
) -> dict:
    """音声認識を実行し、Whisper 互換の {"segments": [...], "text": str} を返す。

    各 segment は start / end / text を持ち、word_timestamps=True なら
    words（start / end / word）も含む。この形は既存アプリの出力と互換。
    """
    if model is None:
        model = load_model(model_size, backend=backend, cache=cache_model)

    if _is_faster_whisper(model):
        return _transcribe_faster(model, media_path, language, word_timestamps)

    result = model.transcribe(
        media_path, language=language, word_timestamps=word_timestamps
    )
    return {"segments": result["segments"], "text": result.get("text", "")}


def _is_faster_whisper(model) -> bool:
    return type(model).__module__.startswith("faster_whisper")


def _transcribe_faster(model, media_path, language, word_timestamps) -> dict:
    segments_iter, _info = model.transcribe(
        media_path, language=language, word_timestamps=word_timestamps
    )

    segments = []
    for seg in segments_iter:
        item = {
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text,
        }
        if word_timestamps and seg.words:
            item["words"] = [
                {"start": float(w.start), "end": float(w.end), "word": w.word}
                for w in seg.words
            ]
        segments.append(item)

    return {"segments": segments, "text": "".join(s["text"] for s in segments)}
