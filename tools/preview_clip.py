"""Ciclo real da Fonte A com layout em teste: clip da Twitch -> download ->
corte -> render -> QC -> Telegram do dono (sem Buffer, sem post público).

Uso local (lê .env):
  python3 -m tools.preview_clip --streamer alanzoka --layout blur
  python3 -m tools.preview_clip --streamer felps --layout blur --no-send

Exit: 0 enviou (ou --no-send ok), 1 falhou.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from config.settings import DB_PATH, FACTORY_DATA  # noqa: E402
from factory import clips as _clips  # noqa: E402
from factory import pack_redes as _pack  # noqa: E402
from factory import qc as _qc  # noqa: E402


def _send_video(mp4: Path, caption: str) -> bool:
    import requests

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not (token and chat):
        print("sem Telegram — vídeo salvo local (sem envio)")
        return False
    with open(mp4, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendVideo",
            data={"chat_id": chat, "caption": caption[:1000]},
            files={"video": (mp4.name, f, "video/mp4")},
            timeout=300,
        )
    print("Telegram sendVideo:", r.status_code)
    if r.status_code == 200:
        return True
    with open(mp4, "rb") as f:
        r2 = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat, "caption": caption[:1000]},
            files={"document": (mp4.name, f, "video/mp4")},
            timeout=300,
        )
    print("Telegram sendDocument:", r2.status_code)
    return r2.status_code == 200


def _clip_meta(day_dir: Path) -> dict:
    try:
        clips = json.loads((day_dir / "clips.json").read_text(encoding="utf-8"))
        return clips[0] if clips else {}
    except Exception:
        return {}


def main(argv: list[str]) -> int:
    streamer = ""
    layout = "blur"
    enviar = True
    if "--streamer" in argv:
        streamer = argv[argv.index("--streamer") + 1].strip().lstrip("@")
    if "--layout" in argv:
        layout = argv[argv.index("--layout") + 1].strip().lower()
    if "--no-send" in argv:
        enviar = False
    if not streamer:
        print("uso: preview_clip --streamer <handle> [--layout blur] [--no-send]")
        return 1
    os.environ["VIRACLIPE_LAYOUT"] = layout

    from tools import seed_whitelist as _seed

    _seed.seed(DB_PATH)
    _seed.activate(streamer, "twitch", DB_PATH)

    day = _dt.date.today().isoformat()
    day_dir = FACTORY_DATA / day
    print(f"ciclo: {streamer} | layout={layout} | dia={day}")
    finais = _clips.process_clips_day(day, DB_PATH, FACTORY_DATA,
                                      max_n=1, keys=["teste"])
    if not finais:
        print("ciclo: nenhum final (sem clip novo ou download falhou).")
        return 1
    if _qc.main(day, FACTORY_DATA, DB_PATH) != 0:
        print("QC falhou — vídeo não enviado.")
        return 1

    c = finais[0]
    meta = _clip_meta(day_dir)
    mp4 = Path(c["mp4"])
    cap, _ = _pack.caption_for(c, "instagram")
    caption = (
        f"🧪 TESTE layout {layout} 9:16 — Fonte A (clip da comunidade)\n"
        f"@{c.get('streamer')} — {c.get('titulo')} "
        f"({float(meta.get('duracao') or 0):.0f}s, {int(meta.get('views') or 0)} views)\n"
        f"{meta.get('url') or ''}\n\n"
        f"Legenda do post:\n{cap}\n\n"
        "Aprovar? Responda OK que eu aplico em TODOS os vídeos (clips + VOD)."
    )
    print(f"final: {mp4} ({mp4.stat().st_size / 1e6:.1f} MB)")
    if not enviar:
        print("--no-send: não enviado.")
        return 0
    return 0 if _send_video(mp4, caption) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
