"""
ffmpeg_tools.py — ffmpeg の場所を一元管理する

moviepy は imageio-ffmpeg が同梱する ffmpeg バイナリを使うが、pydub は
PATH 上の `ffmpeg` を探しに行く。そのため PATH に ffmpeg が無い環境
（Hugging Face Spaces など）では「解析はできるのに書き出しだけ失敗する」
という分かりにくい壊れ方をする。

ここで両者に同じバイナリを使わせて、その差を無くす。
"""

from __future__ import annotations

import functools
import shutil


@functools.lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    """使用する ffmpeg の実行パス。

    imageio-ffmpeg が同梱するバイナリを優先する（どの環境でも必ず存在するため）。
    取得できない場合のみ PATH 上のものにフォールバックする。
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


@functools.lru_cache(maxsize=1)
def configure_pydub() -> str:
    """pydub が使う ffmpeg を明示的に設定する。

    pydub を使う処理の直前に毎回呼んでよい（結果はキャッシュされる）。
    """
    exe = ffmpeg_exe()
    try:
        from pydub import AudioSegment

        AudioSegment.converter = exe
        AudioSegment.ffmpeg = exe

        # ffprobe は imageio-ffmpeg に同梱されていないので、PATH にあるときだけ設定する。
        # 無くても pydub は動く（形式の自動判定が効かなくなるだけ）。
        probe = shutil.which("ffprobe")
        if probe:
            AudioSegment.ffprobe = probe
    except ImportError:
        pass

    return exe
