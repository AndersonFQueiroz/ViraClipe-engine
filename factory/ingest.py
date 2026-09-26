"""Ingest pós-live: yt-dlp 720p + chat replay -> data/<dia>/raw/.

Baixa, registra em vods_processados e deixa o mp4 pronto p/ signals.
Apagar o raw é responsabilidade do run_diaria após o pack (não aqui).
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
import threading
from pathlib import Path

from . import db as _db

YDL_FORMAT = "bv*[height<=720]+ba/b[height<=720]/b"
YDL_FORMAT_LOW = "bv*[height<=480]+ba/b[height<=480]/b"
CHAT_TIMEOUT = 240


def vod_paths(day_dir: Path, video_id: str) -> tuple[Path, Path]:
    raw = day_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in video_id)
    return raw / f"{safe}.mp4", raw / f"{safe}.chat.json"


def _try_format(url: str, out_mp4: Path, fmt: str, runner, extra: list[str] | None = None) -> tuple[bool, str]:
    cmd = (["yt-dlp", "-f", fmt, "--no-playlist", "--no-warnings"]
           + (extra or []) + ["-o", str(out_mp4), url])
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=3600)
        ok = r.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 100_000
        err = "" if ok else (getattr(r, "stderr", "") or "")[-300:]
        return ok, err
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:300]


ANDROID_ARGS = ["--extractor-args", "youtube:player_client=android"]


def download_vod(url: str, out_mp4: Path, runner=subprocess.run) -> bool:
    tentativas = [
        ("720p", YDL_FORMAT, []),
        ("720p-android", YDL_FORMAT, ANDROID_ARGS),
        ("480p-android", YDL_FORMAT_LOW, ANDROID_ARGS),
    ]
    err = ""
    for nome, fmt, extra in tentativas:
        ok, err = _try_format(url, out_mp4, fmt, runner, extra)
        if ok:
            return True
        print(f"ingest: {nome} falhou ({err.strip()[:160]})")
    print(f"ingest: download falhou ({err.strip()[:200]})")
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


def _safe_chat(chat_dl, url: str, chat: Path) -> bool:
    try:
        return bool(chat_dl(url, chat))
    except Exception as exc:
        print(f"ingest: chat falhou ({type(exc).__name__}) — seguindo sem chat")
        try:
            chat.write_text("[]", encoding="utf-8")
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
            print(f"ingest: {vid} download falhou — pulando")
            continue
        try:
            print(f"ingest: {vid} mp4 {mp4.stat().st_size // 1024}KB ok")
        except Exception:
            pass
        if not chat.exists():
            # chat-downloader tem retry interno agressivo: isola em thread
            # daemon com timeout para não sequestrar a diária.
            holder: dict = {}
            t = threading.Thread(target=lambda: holder.update(
                r=_safe_chat(chat_dl, url, chat)), daemon=True)
            t.start()
            t.join(CHAT_TIMEOUT)
            if t.is_alive():
                print(f"ingest: {vid} chat timeout {CHAT_TIMEOUT}s — seguindo sem chat")
                try:
                    chat.write_text("[]", encoding="utf-8")
                except Exception:
                    pass
            else:
                print(f"ingest: {vid} chat {'ok' if holder.get('r') else 'vazio/falhou'}")
        register_vod(db_path, vid, str(v.get("plataforma") or ""), str(v.get("streamer") or ""))
        prontos.append({**v, "mp4": str(mp4), "chat": str(chat)})
    (day_dir / "ingest.json").write_text(
        json.dumps(prontos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return prontos
