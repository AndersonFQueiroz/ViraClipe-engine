"""Render MVP: título hook + crédito queimados via ffmpeg drawtext.

Sem libass, sem TTS, sem Ken Burns (Fase 2). Se drawtext falhar
(sem fonte no Termux), mantém o mp4 do cutter sem quebrar o dia.
Legendas palavra-a-palavra ficam para Fase 1.1.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⬅-⬏]+")


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


def render_corte(mp4_in: Path, titulo: str, streamer: str, vod_url: str,
                 out_mp4: Path, runner=subprocess.run) -> bool:
    hook = safe_text(titulo)[:70] or f"Melhor momento de @{streamer}"
    credit = safe_text(f"@{streamer} — {vod_url}")[:90]
    font = _font()
    if font is None:
        try:
            shutil.copy(mp4_in, out_mp4)
            return True
        except Exception:
            return False
    vf = (
        f"drawtext=fontfile={font}:text='{hook}':fontsize=44:fontcolor=white:"
        f"borderw=2:bordercolor=black:x=(w-text_w)/2:y=140,"
        f"drawtext=fontfile={font}:text='{credit}':fontsize=26:fontcolor=white:"
        f"borderw=1:bordercolor=black:x=(w-text_w)/2:y=h-120"
    )
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
                         str(c.get("url") or ""), dst, runner=runner)
        if dst.exists():
            finais.append({**c, "mp4": str(dst)})
    (day_dir / "finais.json").write_text(
        json.dumps(finais, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return finais
