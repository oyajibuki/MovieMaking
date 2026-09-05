"""
cli.py — AutoCutter PRO のコマンドライン版

例:
  python cli.py input.mp4 -o output.mp4 --pitch 4 --threshold -38 --min-silence 0.5
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from autocutter import audio_analyzer, pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="無音・フィラーを自動カットし、声色を変換する")
    p.add_argument("input", help="入力動画")
    p.add_argument("-o", "--output", help="出力 mp4（既定: <入力名>_cut.mp4）")
    p.add_argument("--srt", help="出力する SRT のパス（省略時は出力しない）")

    p.add_argument("--no-silence", action="store_true", help="無音カットを無効化")
    p.add_argument("--threshold", type=float, default=-38.0, help="無音とみなす dBFS（既定 -38）")
    p.add_argument("--min-silence", type=float, default=0.5, help="無音とみなす最短秒数（既定 0.5）")

    p.add_argument("--no-filler", action="store_true", help="フィラーカットを無効化")
    p.add_argument("--fillers", help="カットする単語（カンマ区切り）")

    p.add_argument("--margin", type=float, default=0.08, help="カット前後に残す余白の秒数（既定 0.08）")
    p.add_argument("--pitch", type=float, default=0.0, help="ピッチ変化量（半音、既定 0）")
    p.add_argument("--pitch-method", choices=["librosa", "pydub"], default="librosa")

    p.add_argument("--model", default="base", help="Whisper モデル（既定 base）")
    p.add_argument("--language", default="ja", help="音声の言語（既定 ja）")
    p.add_argument("--dry-run", action="store_true", help="解析のみ行い、動画は書き出さない")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.exists(args.input):
        print(f"入力が見つかりません: {args.input}", file=sys.stderr)
        return 1

    output = args.output or f"{os.path.splitext(args.input)[0]}_cut.mp4"

    fillers = (
        [w.strip() for w in args.fillers.replace("、", ",").split(",") if w.strip()]
        if args.fillers
        else list(audio_analyzer.DEFAULT_FILLER_WORDS_JA)
    )

    settings = pipeline.CutSettings(
        remove_silence=not args.no_silence,
        silence_threshold_db=args.threshold,
        min_silence_len=args.min_silence,
        remove_fillers=not args.no_filler,
        filler_words=fillers,
        margin=args.margin,
        pitch_shift_semitones=args.pitch,
        pitch_method=args.pitch_method,
        model_size=args.model,
        language=args.language,
    )

    def report(ratio, message):
        print(f"[{ratio * 100:5.1f}%] {message}")

    with tempfile.TemporaryDirectory(prefix="autocutter_") as work_dir:
        result = pipeline.analyze(args.input, settings, work_dir, progress_callback=report)

        print(
            f"\n元の長さ {result.original_duration:.2f}s → 編集後 {result.new_duration:.2f}s "
            f"({result.removed_ratio * 100:.1f}% カット / "
            f"無音 {len(result.silence_cuts)} 箇所, フィラー {len(result.filler_cuts)} 箇所)"
        )

        if args.srt:
            with open(args.srt, "w", encoding="utf-8") as f:
                f.write(result.srt())
            print(f"SRT を書き出しました: {args.srt}")

        if args.dry_run:
            return 0

        pipeline.render(args.input, result, settings, output, work_dir, report)
        print(f"書き出しました: {output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
