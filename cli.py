"""
cli.py — AutoCutter PRO のコマンドライン版

動画でも音声のみ（mp3 / m4a / wav / flac / ogg など）でも扱える。

例:
  python cli.py input.mp4 -o output.mp4 --pitch 4 --threshold -38 --min-silence 0.5
  python cli.py input.m4a --pitch 4 --srt output.srt
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from autocutter import ai_voice, audio_analyzer, pipeline, video_editor, voice_changer


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="無音・フィラーを自動カットし、声色を変換する（動画・音声どちらも可）"
    )
    # --list-voices だけを単体で使えるように任意扱いにする
    p.add_argument("input", nargs="?", help="入力ファイル（動画 または 音声）")
    p.add_argument(
        "-o", "--output",
        help="出力パス（既定: <入力名>_cut.<入力と同じ拡張子>）。"
             "音声入力の場合は拡張子で出力形式が決まる",
    )
    p.add_argument("--srt", help="出力する SRT のパス（省略時は出力しない）")

    p.add_argument("--no-silence", action="store_true", help="無音カットを無効化")
    p.add_argument(
        "--sensitivity", type=float, default=16.0,
        help="素材の平均音量から何 dB 下を無音とみなすか（既定 16）。"
             "カットされ過ぎるときは大きくする",
    )
    p.add_argument(
        "--threshold", type=float, default=None,
        help="無音とみなす dBFS を固定値で指定する（指定すると --sensitivity は無視される）",
    )
    p.add_argument("--min-silence", type=float, default=0.5, help="無音とみなす最短秒数（既定 0.5）")

    p.add_argument("--no-filler", action="store_true", help="フィラーカットを無効化")
    p.add_argument("--fillers", help="カットする単語（カンマ区切り）")

    p.add_argument("--margin", type=float, default=0.08, help="カット前後に残す余白の秒数（既定 0.08）")
    p.add_argument(
        "--voice", default=None,
        help="声色プリセット名（例: 女性の声 / 太い男の声 / 子供の声）。"
             "--list-voices で一覧を表示",
    )
    p.add_argument(
        "--voice-strength", type=float, default=1.0,
        help="プリセットの変化の強さ（既定 1.0）",
    )
    p.add_argument("--pitch", type=float, default=0.0, help="ピッチ変化量（半音、既定 0）")
    p.add_argument(
        "--formant", type=float, default=1.0,
        help="フォルマント倍率（既定 1.0）。1 より大きいと細い声、小さいと太い声",
    )
    p.add_argument("--list-voices", action="store_true", help="声色プリセットの一覧を表示して終了")
    p.add_argument(
        "--ai-voice", default=None,
        help="AI で別人の声に置き換える。macOS 組み込み音声名（例: Kyoko）"
             "または参照音声ファイルのパス",
    )
    p.add_argument(
        "--ai-steps", type=int, default=25,
        help="AI 変換の拡散ステップ数（既定 25）。多いほど高品質だが遅い",
    )

    p.add_argument("--model", default="base", help="Whisper モデル（既定 base）")
    p.add_argument("--language", default="ja", help="音声の言語（既定 ja）")
    p.add_argument("--dry-run", action="store_true", help="解析のみ行い、動画は書き出さない")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_voices:
        print("信号処理のプリセット（--voice）:")
        for name, preset in voice_changer.VOICE_PRESETS.items():
            target = f"{preset['target_f0']:.0f} Hz" if preset["target_f0"] else "—"
            print(f"  {name:24s} 目標の高さ {target:>8s} / フォルマント {preset['formant']:.2f} 倍")

        print()
        if ai_voice.is_available():
            print("AI 声質変換で使える組み込みの声（--ai-voice）:")
            for label, name in ai_voice.available_builtin_voices().items():
                print(f"  {name:12s} {label}")
            print("  （参照音声ファイルのパスを直接指定することもできます）")
        else:
            print(f"AI 声質変換: 未導入 — {ai_voice.unavailable_reason()}")
        return 0

    if not args.input:
        build_parser().print_usage(sys.stderr)
        print("入力ファイルを指定してください。", file=sys.stderr)
        return 1

    if not os.path.exists(args.input):
        print(f"入力が見つかりません: {args.input}", file=sys.stderr)
        return 1

    # 音声のみの入力なら、出力も同じ形式に揃える
    if args.output:
        output = args.output
    elif video_editor.is_audio_only(args.input):
        ext = video_editor.supported_output_extension(args.input)
        output = f"{os.path.splitext(args.input)[0]}_cut{ext}"
    else:
        output = f"{os.path.splitext(args.input)[0]}_cut.mp4"

    fillers = (
        [w.strip() for w in args.fillers.replace("、", ",").split(",") if w.strip()]
        if args.fillers
        else list(audio_analyzer.DEFAULT_FILLER_WORDS_JA)
    )

    # --ai-voice はファイルパスとしても組み込み音声名としても受け取る
    ai_reference = ai_builtin = None
    if args.ai_voice:
        if os.path.exists(args.ai_voice):
            ai_reference = args.ai_voice
        else:
            ai_builtin = args.ai_voice
        if not ai_voice.is_available():
            print(f"AI 声質変換を使えません: {ai_voice.unavailable_reason()}", file=sys.stderr)
            return 1

    settings = pipeline.CutSettings(
        remove_silence=not args.no_silence,
        silence_threshold_db=args.threshold if args.threshold is not None else -38.0,
        silence_auto_threshold=args.threshold is None,
        silence_relative_offset_db=args.sensitivity,
        min_silence_len=args.min_silence,
        remove_fillers=not args.no_filler,
        filler_words=fillers,
        margin=args.margin,
        voice_preset=args.voice or voice_changer.DEFAULT_PRESET,
        voice_strength=args.voice_strength,
        manual_voice=args.voice is None and (args.pitch or args.formant != 1.0),
        pitch_shift_semitones=args.pitch,
        formant_ratio=args.formant,
        ai_builtin_voice=ai_builtin,
        ai_reference_wav=ai_reference,
        ai_diffusion_steps=args.ai_steps,
        model_size=args.model,
        language=args.language,
    )

    def report(ratio, message):
        print(f"[{ratio * 100:5.1f}%] {message}")

    with tempfile.TemporaryDirectory(prefix="autocutter_") as work_dir:
        result = pipeline.analyze(args.input, settings, work_dir, progress_callback=report)

        kind = "音声" if result.is_audio_only else "動画"
        print(
            f"\n平均音量 {result.average_loudness_db:.1f} dBFS / "
            f"無音の閾値 {result.effective_threshold_db:.1f} dBFS"
        )
        print(
            f"[{kind}] 元の長さ {result.original_duration:.2f}s "
            f"→ 編集後 {result.new_duration:.2f}s "
            f"({result.removed_ratio * 100:.1f}% カット / "
            f"無音 {len(result.silence_cuts)} 箇所, フィラー {len(result.filler_cuts)} 箇所)"
        )

        if result.source_f0:
            semitones, formant = settings.resolve_voice(result.source_f0)
            reached = result.source_f0 * 2 ** (semitones / 12)
            print(
                f"声の高さ {result.source_f0:.0f} Hz"
                + (f" -> {reached:.0f} Hz（{semitones:+.1f} 半音 / "
                   f"フォルマント {formant:.2f} 倍）" if semitones or formant != 1.0 else "")
            )

        if result.removed_ratio > 0.6:
            print(
                "⚠️  6 割以上カットされています。喋っている部分まで無音と"
                "判定されている可能性があります。--sensitivity を大きくしてください。"
            )

        if args.srt:
            with open(args.srt, "w", encoding="utf-8") as f:
                f.write(result.srt())
            print(f"SRT を書き出しました: {args.srt}")

        if args.dry_run:
            return 0

        # 出力形式が書き出し時に変わることがあるので、実際のパスを受け取る
        output = pipeline.render(args.input, result, settings, output, work_dir, report)
        print(f"書き出しました: {output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
