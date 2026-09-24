"""Log do pack no Telegram do dono (sem aprovação — auto-total).

Sem TELEGRAM_BOT_TOKEN/OWNER retorna exit 3 com pack salvo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from . import net as _net


def main(day: str, factory_data: Path) -> int:
    day_dir = factory_data / day
    pack = json.loads((day_dir / "pack.json").read_text(encoding="utf-8"))
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not (token and chat):
        print(f"SEM TELEGRAM — pack pronto em {day_dir}/pack.json (exit 3).")
        return 3
    api = f"https://api.telegram.org/bot{token}"
    s = requests.Session()

    def _send_video(path: str, caption: str) -> None:
        with open(path, "rb") as f:
            def _do():
                r = s.post(f"{api}/sendVideo", data={"chat_id": chat, "caption": caption[:1000]},
                           files={"video": (Path(path).name, f, "video/mp4")}, timeout=180)
                r.raise_for_status()
                return r.json()
            _net.call(_do)

    for key, vpath in pack.get("videos", {}).items():
        cred = pack.get("creditos", {}).get(key, {})
        _send_video(vpath, f"{key} {pack.get('titles', {}).get(key,'')}\n{pack['captions'][key][:800]}")
    kwai = day_dir / "pack_kwai.zip"
    if kwai.exists() and kwai.stat().st_size < 45_000_000:
        with open(kwai, "rb") as f:
            def _doc():
                r = s.post(f"{api}/sendDocument", data={"chat_id": chat, "caption": "Kwai manual"},
                           files={"document": (kwai.name, f, "application/zip")}, timeout=180)
                r.raise_for_status()
                return r.json()
            _net.call(_doc)
    print("Pack logado no Telegram.")
    return 0
