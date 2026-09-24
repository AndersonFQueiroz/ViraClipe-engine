"""Ingest pós-live: yt-dlp 720p + chat replay -> data/<dia>/raw/.

Baixa, registra em vods_processados e deixa o mp4 pronto p/ signals.
Apagar o raw é responsabilidade do run_diaria após o pack (não aqui).
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path

from . import db as _db

YDL_FORMAT = "bv*[height<=720]+ba/b[height<=720]/b"


def vod_paths(day_dir: Path, video_id: str) -> tuple[Path, Path]:
    raw = day_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in video_id)
    return raw / f"{safe}.mp4", raw / f"{safe}.chat.json"


def download_vod(url: str, out_mp4: Path, runner=subprocess.run) -> bool:
    cmd = [
        "yt-dlp", "-f", YDL_FORMAT, "--no-playlist",
        "--no-warnings", "-o", str(out_mp4), url,
    ]
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=3600)
        return r.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 100_000
    except Exception:
        return False


def download_chat(url: str, out_chat: Path) -> bool:
    """Chat replay via chat-downloader (free). Falha silenciosa -> []."""
    try:
        from chat_downloader import ChatDownloader  # type: ignore
    except Exception:
        out_chat.write_text("[]", encoding="utf-8")
        return False
    try:
        msgs = []
        for m in ChatDownloader().get_chat(url, max_messages=20000):
            msgs.append({
                "t": float(m.get("time_in_seconds") or 0),
                "msg": str(m.get("message") or "")[:200],
                "emotes": len(m.get("emotes") or []),
            })
        out_chat.write_text(json.dumps(msgs, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        try:
            out_chat.write_text("[]", encoding="utf-8")
        except Exception:
            pass
        return False


def register_vod(
    db_path: Path, video_id: str, plataforma: str, streamer: str, duracao: float = 0
) -> None:
    con = _db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO vods_processados(video_id, plataforma, streamer, duracao, baixado_em)"
            " VALUES(?,?,?,?,?)",
            (video_id, plataforma, streamer, duracao, _dt.date.today().isoformat()),
        )
        con.commit()
    finally:
        con.close()


def ingest_day(
    day: str,
    db_path: Path,
    factory_data: Path,
    downloader=None,
    chat_downloader=None,
) -> list[dict]:
    day_dir = factory_data / day
    vods_path = day_dir / "vods.json"
    if not vods_path.exists():
        return []
    vods = json.loads(vods_path.read_text(encoding="utf-8"))
    downloader = downloader or download_vod
    chat_dl = chat_downloader or download_chat
    prontos: list[dict] = []
    for v in vods:
        vid = str(v.get("video_id") or "")
        if not vid:
            continue
        mp4, chat = vod_paths(day_dir, vid)
        url = str(v.get("url") or "")
        ok = mp4.exists() and mp4.stat().st_size > 100_000
        if not ok and url:
            ok = bool(downloader(url, mp4))
        if not ok:
            continue
        if not chat.exists():
            try:
                chat_dl(url, chat)
            except Exception:
                pass
        register_vod(db_path, vid, str(v.get("plataforma") or ""), str(v.get("streamer") or ""))
        prontos.append({**v, "mp4": str(mp4), "chat": str(chat)})
    (day_dir / "ingest.json").write_text(
        json.dumps(prontos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return prontos
