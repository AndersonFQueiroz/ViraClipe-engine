"""Sobe mp4 p/ URL pública (Buffer exige link, não upload direto).

Catbox (permanente) -> fallback Litterbox (72h). Port ReelIfy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

from . import net as _net

_TIMEOUT = 120
MIN_BYTES = 100_000


def _post(files: dict, data: dict, url: str) -> str | None:
    try:
        r = _net.post(requests.Session(), url, files=files, data=data, timeout=_TIMEOUT)
        body = r.text.strip()
        if body.startswith("https://"):
            return body
        print(f"host falhou ({url}): {r.status_code} {body[:100]}")
    except Exception as exc:
        print(f"host erro ({url}): {exc}")
    return None


def head_ok(url: str) -> bool:
    try:
        r = _net.call(requests.head, url, timeout=30, allow_redirects=True)
        if r.status_code != 200:
            return False
        return int(r.headers.get("content-length") or 0) >= MIN_BYTES
    except Exception:
        return False


def upload(path: Path) -> str | None:
    with open(path, "rb") as f:
        blob = f.read()
    url = _post({"fileToUpload": (path.name, blob, "video/mp4")},
                {"reqtype": "fileupload"}, "https://catbox.moe/user/api.php")
    if url:
        return url
    return _post({"fileToUpload": (path.name, blob, "video/mp4")},
                 {"reqtype": "fileupload", "time": "72h"},
                 "https://litterbox.catbox.moe/resources/internals/api.php")


def telegram_host(path: Path) -> str | None:
    """Host via Telegram p/ validadores exigentes (TikTok). Apaga msg após."""
    import os

    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not (token and chat):
        return None
    try:
        s = requests.Session()
        with open(path, "rb") as f:
            r = _net.post(s, f"https://api.telegram.org/bot{token}/sendVideo",
                          data={"chat_id": chat, "caption": "host temporário (apagando)"},
                          files={"video": (path.name, f, "video/mp4")}, timeout=180).json()
        mid = r["result"]["message_id"]
        fid = r["result"]["video"]["file_id"]
        g = _net.post(s, f"https://api.telegram.org/bot{token}/getFile",
                      params={"file_id": fid}, timeout=30).json()
        url = f"https://api.telegram.org/file/bot{token}/{g['result']['file_path']}"
        if not head_ok(url):
            return None
        try:
            s.post(f"https://api.telegram.org/bot{token}/deleteMessage",
                   json={"chat_id": chat, "message_id": mid}, timeout=30)
        except Exception:
            pass
        return url
    except Exception as exc:
        print(f"telegram host falhou: {exc}")
        return None


if __name__ == "__main__":
    out = upload(Path(sys.argv[1]))
    print(out or "FALHA")
    raise SystemExit(0 if out else 1)
