"""
subtitle_utils.py — 字幕出力モジュール

04.subtitle（AI Subtitle）の SRT / ASS 出力ロジックを流用し、
DataFrame ではなく dict のリストでも扱えるようにしたもの。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Sequence


def format_timestamp(seconds: float) -> str:
    """SRT 用タイムスタンプ（HH:MM:SS,mmm）。"""
    td = timedelta(seconds=max(0.0, float(seconds)))
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int(td.microseconds / 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def format_timestamp_ass(seconds: float) -> str:
    """ASS 用タイムスタンプ（H:MM:SS.cc）。"""
    td = timedelta(seconds=max(0.0, float(seconds)))
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    centis = int(td.microseconds / 10000)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def _iter_rows(segments) -> Iterable[dict]:
    """dict のリストでも pandas.DataFrame でも同じように回せるようにする。"""
    if hasattr(segments, "iterrows"):
        for _, row in segments.iterrows():
            yield row
    else:
        yield from segments


def create_srt_content(segments) -> str:
    """字幕セグメントから SRT 文字列を生成する。"""
    lines = []
    for idx, row in enumerate(_iter_rows(segments), start=1):
        text = str(row["text"]).strip()
        if not text:
            continue
        lines.append(
            f"{idx}\n{format_timestamp(row['start'])} --> {format_timestamp(row['end'])}\n{text}\n"
        )
    return "\n".join(lines)


def hex_to_ass_color(hex_color: str) -> str:
    """#RRGGBB → ASS の &HAABBGGRR 形式。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "&H00FFFFFF"
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H00{b}{g}{r}".upper()


def create_ass_content(
    segments,
    font_name: str = "MS Gothic",
    font_size: int = 40,
    primary_color: str = "&H00FFFFFF",
    outline_color: str = "&H00000000",
    outline_width: int = 2,
    shadow_depth: int = 0,
    alignment: int = 2,
    margin_v: int = 20,
) -> str:
    """字幕セグメントから ASS 字幕（装飾付き）を生成する。"""
    header = f"""[Script Info]
Title: AutoCutter PRO
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},&H00000000,0,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = ""
    for row in _iter_rows(segments):
        text = str(row["text"]).strip().replace("\n", "\\N")
        if not text:
            continue
        start = format_timestamp_ass(row["start"])
        end = format_timestamp_ass(row["end"])
        events += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"

    return header + events


def segments_to_rows(segments: Sequence[dict]) -> list[dict]:
    """Whisper のセグメントから start/end/text だけを抜き出す。"""
    return [
        {
            "start": float(s["start"]),
            "end": float(s["end"]),
            "text": str(s.get("text", "")).strip(),
        }
        for s in segments
    ]
