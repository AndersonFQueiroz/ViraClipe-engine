"""Teste de reframe com 1 corte: baixa 90s da VOD, corta split/centro e manda no Telegram.

Zero Gemini (sem quota): só yt-dlp + ffmpeg + OpenCV + Telegram.
Uso no Actions via workflow_dispatch (tools + workflow) ou local:
  python3 -m tools.reframe_check <vod_url> <t_ini> <dur>

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID.
Exit: 0 enviou, 1 falhou.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from factory import cutter as _cut
from factory import reframe as _rf


def _send_video(mp4: Path, caption: str) -> bool:
    import os

    import requests

    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not (token and chat):
        print("sem Telegram — vídeo salvo (sem envio)")
        return False
    with open(mp4, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                          data={"chat_id": chat, "caption": caption[:1000]},
                          files={"video": (mp4.name, f, "video/mp4")}, timeout=180)
        print("Telegram:", r.status_code)
        return r.status_code == 200


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print("uso: reframe_check <vod_url> <t_ini> <dur>")
        return 1
    url, t_ini, dur = argv[1], float(argv[2]), float(argv[3])
    work = Path(tempfile.mkdtemp(prefix="reframe-check-"))
    src = work / "src.mp4"
    print(f"baixando 95s de {url} @ {t_ini}s ...")
    g = subprocess.run(
        ["yt-dlp", "-g", "-f", "bv*[height<=720]+ba/b[height<=720]/b",
         "--no-playlist", "--no-warnings", url],
        capture_output=True, text=True, timeout=300,
    )
    stream = (g.stdout or "").strip().splitlines()
    if g.returncode != 0 or not stream:
        print(f"yt-dlp -g falhou: {(g.stderr or '')[-300:]}")
        return 1
    dl = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", stream[0], "-ss", f"{t_ini:.0f}", "-t", "95",
         "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-c:a", "aac", str(src)],
        capture_output=True, text=True, timeout=900,
    )
    if dl.returncode != 0 or not src.exists() or src.stat().st_size < 100_000:
        print(f"ffmpeg seek falhou: {(dl.stderr or '')[-300:]}")
        return 1
    box = _rf.find_face_box(src, 5.0, min(dur, 60.0))
    layout = "split" if box else "centro"
    print(f"rosto: {'SIM ' + str(box) if box else 'NÃO — fallback centro'}")
    out = work / f"teste-{layout}.mp4"
    if not _cut.cut_corte(src, 5.0, min(dur, 60.0), out, face_box=box):
        print("corte falhou")
        return 1
    ok = _send_video(out, f"🧪 TESTE reframe ({layout}): 1 corte, rostos só se detectados. t={t_ini}s")
    print("OK" if ok else "SEM ENVIO")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
