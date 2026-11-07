"""Render: só clipe + marca d'água anti-kiba via ffmpeg drawtext.

Nada de texto queimado além da marca: hook, crédito e link da live vão
na DESCRIÇÃO do post (pack), não no vídeo. Marca: handle semi-transparente
o vídeo todo, alternando topo/base a cada 6s (crop de um canto não limpa).
Com `fg_box` (layout blur), a marca fica SEMPRE sobre o vídeo original —
cortar a faixa borrada não remove a marca.
Sem fonte no host, copia sem quebrar o dia.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⬅-⬏]+")
WM_MARGIN = 24


def safe_text(text: str) -> str:
    text = _EMOJI_RE.sub("", text or "")
    return " ".join(text.split())


def _font() -> str | None:
    for cand in (
        Path("assets/fonts/Poppins-SemiBold.ttf"),
        Path("/system/fonts/DroidSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ):
        if cand.exists():
            return str(cand)
    return None


def _ff_esc(text: str) -> str:
    """Escapa texto p/ drawtext (':' separa opções, "'" fecha string)."""
    return (text or "").replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")


def handle_ativo() -> str:
    try:
        from config.secret_loader import get_handle
        return get_handle()
    except Exception:
        return "@viraclipe.oficial"


def build_overlay_vf(font: str, hook: str = "", credit: str = "", handle: str = "",
                     fg_box: tuple[int, int, int, int] | None = None) -> str:
    """Monta o -vf: SÓ a marca alternada anti-kiba (sem texto queimado).

    fg_box = (x, y, w, h) do vídeo original dentro do 720x1280 (layout blur).
    Com ele a marca fica DENTRO do vídeo: recortar o blur não limpa a marca.
    """
    w = _ff_esc(safe_text(handle or handle_ativo())[:30] or "@viraclipe.oficial")
    x_expr, y_top, y_bot = "(w-text_w)/2", "60", "h-220"
    if fg_box:
        fx, fy, fw, fh = (int(v) for v in fg_box)
        x_expr = f"{fx}+({fw}-text_w)/2"
        y_top = str(fy + WM_MARGIN)
        y_bot = f"{fy + fh - WM_MARGIN}-text_h"
    # Marca: 6s no topo, 6s na base, loop. Alpha 0.55: legível, não polui.
    wm_top = (
        f"drawtext=fontfile={font}:text='{w}':fontsize=28:"
        f"fontcolor=white@0.55:borderw=1:bordercolor=black@0.5:"
        f"x={x_expr}:y={y_top}:enable='lt(mod(t,12),6)'"
    )
    wm_bot = (
        f"drawtext=fontfile={font}:text='{w}':fontsize=28:"
        f"fontcolor=white@0.55:borderw=1:bordercolor=black@0.5:"
        f"x={x_expr}:y={y_bot}:enable='gte(mod(t,12),6)'"
    )
    return f"{wm_top},{wm_bot}"


def render_corte(mp4_in: Path, titulo: str, streamer: str, vod_url: str,
                  out_mp4: Path, runner=subprocess.run,
                  fg_box: tuple[int, int, int, int] | None = None) -> bool:
    font = _font()
    if font is None:
        try:
            shutil.copy(mp4_in, out_mp4)
            return True
        except Exception:
            return False
    vf = build_overlay_vf(font, fg_box=fg_box)
    try:
        r = runner(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(mp4_in), "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "copy", "-movflags", "+faststart", str(out_mp4)],
            capture_output=True, text=True, timeout=900,
        )
        if r.returncode == 0 and out_mp4.exists():
            return True
        shutil.copy(mp4_in, out_mp4)
        return True
    except Exception:
        try:
            shutil.copy(mp4_in, out_mp4)
            return True
        except Exception:
            return False


def render_day(day: str, factory_data: Path, runner=subprocess.run) -> list[dict]:
    day_dir = factory_data / day
    cortes = json.loads((day_dir / "cortes.json").read_text(encoding="utf-8"))
    finais: list[dict] = []
    for c in cortes:
        src = Path(c["mp4"])
        dst = day_dir / f"final-{c['cut_id']}.mp4"
        if not (dst.exists() and dst.stat().st_size > 100_000):
            render_corte(src, str(c.get("titulo") or ""), str(c.get("streamer") or ""),
                         str(c.get("url") or ""), dst, runner=runner,
                         fg_box=c.get("fg_box"))
        if dst.exists():
            finais.append({**c, "mp4": str(dst)})
    (day_dir / "finais.json").write_text(
        json.dumps(finais, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return finais
