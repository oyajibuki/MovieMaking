"""
ai_voice.py — AI による声質変換（別人の声への置き換え）

信号処理によるピッチ・フォルマント変換（voice_changer.py）には限界があり、
元の声が低いほど女性や子供の声には届かない。本当に「別人の声」にしたい場合は
AI ベースの声質変換が必要になる。

ここでは seed-vc（zero-shot voice conversion）を使う。参照音声を 1 つ渡すだけで
学習不要でその声に変換でき、話す長さ・間・抑揚は元のまま保たれるため、
カット処理や動画との同期をそのまま活かせる。

seed-vc は GPL-3.0 のため、本体には取り込まず **別プロセス・別仮想環境** として
呼び出す。依存の衝突（numpy や gradio のバージョンが本体と非互換）も同時に避けられる。
未導入の環境では is_available() が False を返し、信号処理方式へフォールバックする。

導入は ./setup_ai_voice.sh で行う。
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

# 参照音声の推奨の長さ（秒）。短すぎると声の特徴を掴めない
MIN_REFERENCE_SEC = 3.0

# macOS 標準の日本語音声。参照音声を手軽に用意するために使う
MACOS_JA_VOICES = {
    "女性 A（Kyoko）": "Kyoko",
    "女性 B（Sandy）": "Sandy",
    "女性 C（Shelley）": "Shelley",
    "男性 A（Eddy）": "Eddy",
    "男性 B（Reed）": "Reed",
    "男性 C（Rocko）": "Rocko",
    "年配の女性（Grandma）": "Grandma",
    "年配の男性（Grandpa）": "Grandpa",
}

# 参照音声を作るために読み上げる文章。音素が偏らないよう少し長めにする
_REFERENCE_TEXT = (
    "こんにちは。今日はとても良い天気ですね。"
    "新しいアプリの開発を進めていて、色々な機能を試しているところです。"
    "動画の編集や音声の処理について、これから詳しく説明していきます。"
    "よろしくお願いします。"
)


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def seed_vc_dir() -> str:
    return os.path.join(project_root(), "vendor", "seed-vc")


def seed_vc_python() -> str:
    return os.path.join(project_root(), ".venv-vc", "bin", "python")


def is_available() -> bool:
    """seed-vc が導入済みかどうか。"""
    return os.path.exists(os.path.join(seed_vc_dir(), "inference.py")) and os.path.exists(
        seed_vc_python()
    )


def unavailable_reason() -> str:
    """導入されていない理由を説明する文字列。"""
    if not os.path.exists(os.path.join(seed_vc_dir(), "inference.py")):
        return "seed-vc が見つかりません。./setup_ai_voice.sh を実行してください。"
    if not os.path.exists(seed_vc_python()):
        return "AI 声質変換用の仮想環境（.venv-vc）がありません。./setup_ai_voice.sh を実行してください。"
    return ""


# --------------------------------------------------------------------------
# 参照音声（変換先の声）
# --------------------------------------------------------------------------

def can_make_builtin_voices() -> bool:
    """macOS の say コマンドで参照音声を作れるか。"""
    return sys.platform == "darwin" and shutil.which("say") is not None


def available_builtin_voices() -> dict[str, str]:
    """この環境で実際に使える組み込み音声（表示名 -> say の音声名）。"""
    if not can_make_builtin_voices():
        return {}

    try:
        listing = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return {}

    installed = {line.split()[0] for line in listing.splitlines() if line.strip()}
    return {
        label: name for label, name in MACOS_JA_VOICES.items() if name in installed
    }


def build_reference(voice_name: str, cache_dir: str) -> str:
    """macOS の音声合成で参照音声（wav）を作る。既にあれば作り直さない。"""
    if not can_make_builtin_voices():
        raise RuntimeError(
            "組み込みの声は macOS でのみ利用できます。"
            "参照音声のファイルをアップロードしてください。"
        )

    os.makedirs(cache_dir, exist_ok=True)
    wav_path = os.path.join(cache_dir, f"ref_{voice_name}.wav")
    if os.path.exists(wav_path):
        return wav_path

    aiff_path = os.path.join(cache_dir, f"ref_{voice_name}.aiff")
    subprocess.run(
        ["say", "-v", voice_name, "-o", aiff_path, _REFERENCE_TEXT],
        check=True,
        capture_output=True,
        timeout=120,
    )

    from . import ffmpeg_tools

    subprocess.run(
        [
            ffmpeg_tools.ffmpeg_exe(), "-y", "-loglevel", "error",
            "-i", aiff_path, "-ar", "22050", "-ac", "1", wav_path,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    os.remove(aiff_path)
    return wav_path


# --------------------------------------------------------------------------
# 変換
# --------------------------------------------------------------------------

def convert(
    source_wav: str,
    reference_wav: str,
    output_wav: str,
    diffusion_steps: int = 25,
    length_adjust: float = 1.0,
    inference_cfg_rate: float = 0.7,
    preserve_intonation: bool = True,
    timeout: int = 3600,
) -> str:
    """source_wav の声を reference_wav の声に変換する。

    話す長さ・間は元のまま保たれるので、カット処理や動画との同期を
    やり直す必要はない。

    Args:
        source_wav: 変換したい音声（wav）
        reference_wav: 変換先の声のサンプル（wav、3 秒以上を推奨）
        output_wav: 出力先
        diffusion_steps: 拡散ステップ数。多いほど高品質だが遅い（25 が既定）
        length_adjust: 1.0 より大きいと間延びする。基本は 1.0 のまま
        inference_cfg_rate: 参照音声への寄せ具合
        preserve_intonation: 元の抑揚（ピッチの上下）を追従させる。
            無効にすると抑揚が 3 割ほど平坦になり機械的に聞こえる。
            実測では抑揚の相関が 0.81 -> 0.99 に改善する。代わりに 3 倍ほど遅い

    Returns:
        output_wav
    """
    if not is_available():
        raise RuntimeError(unavailable_reason())

    if not os.path.exists(reference_wav):
        raise FileNotFoundError(f"参照音声が見つかりません: {reference_wav}")

    ensure_mps_patch()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(output_wav)), "_seedvc")
    os.makedirs(out_dir, exist_ok=True)

    result = subprocess.run(
        [
            seed_vc_python(), "inference.py",
            "--source", os.path.abspath(source_wav),
            "--target", os.path.abspath(reference_wav),
            "--output", out_dir,
            "--diffusion-steps", str(diffusion_steps),
            "--length-adjust", str(length_adjust),
            "--inference-cfg-rate", str(inference_cfg_rate),
            "--f0-condition", "True" if preserve_intonation else "False",
            "--auto-f0-adjust", "True" if preserve_intonation else "False",
        ],
        cwd=seed_vc_dir(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    produced = sorted(glob.glob(os.path.join(out_dir, "*.wav")), key=os.path.getmtime)
    if result.returncode != 0 or not produced:
        tail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"AI 声質変換に失敗しました:\n{tail}")

    shutil.move(produced[-1], output_wav)
    shutil.rmtree(out_dir, ignore_errors=True)
    return output_wav


def ensure_mps_patch() -> bool:
    """Apple Silicon（MPS）で f0-condition が動くように seed-vc を修正する。

    seed-vc は F0 を float64 のまま MPS へ送るが、MPS は float64 を扱えないため
    「Cannot convert a MPS Tensor to float64 dtype」で落ちる。
    vendor/ は git 管理外で再取得され得るので、実行前に毎回確認して当て直す。

    Returns:
        修正を適用した場合 True（既に適用済み・不要なら False）
    """
    path = os.path.join(seed_vc_dir(), "inference.py")
    if not os.path.exists(path):
        return False

    with open(path, encoding="utf-8") as f:
        source = f.read()

    original = (
        "        F0_ori = torch.from_numpy(F0_ori).to(device)[None]\n"
        "        F0_alt = torch.from_numpy(F0_alt).to(device)[None]"
    )
    if original not in source:
        return False  # 既に適用済み、または上流で修正された

    patched = (
        "        # MPS は float64 を扱えないので float32 に落とす（AutoCutter による修正）\n"
        "        F0_ori = torch.from_numpy(F0_ori).float().to(device)[None]\n"
        "        F0_alt = torch.from_numpy(F0_alt).float().to(device)[None]"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(source.replace(original, patched))
    return True
