"""Fonte A: clips criados pela comunidade na Twitch (curadoria humana grátis).

- Descoberta via Helix oficial GET /clips (sem gambiarra GQL).
- views do clip = virality score votado por humanos reais.
- Anti-repetição em 2 camadas (automático, sem curadoria manual):
  1. clip_id exato já visto -> pula;
  2. mesmo vod_id + vod_offset (±OFFSET_TOL) -> dois usuários cliparam
     o mesmo momento com IDs diferentes -> pula.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

from . import db as _db
from . import discovery as _disc

MIN_DUR = 15.0
MAX_DUR = 60.0
OFFSET_TOL = 10.0  # segundos: mesmo momento, clipadores diferentes
DEFAULT_DAYS = 7
DEFAULT_FIRST = 20


def fetch_clips(handle: str, client_id: str = "", client_secret: str = "",
                days: int = DEFAULT_DAYS, first: int = DEFAULT_FIRST,
                http_get=None, http_post=None) -> list[dict]:
    """Clips recentes do canal via Helix. Sem credenciais retorna []."""
    if not (client_id and client_secret):
        return []
    get = http_get or _disc._http_get
    token = _disc._twitch_token(client_id, client_secret, http_post)
    heads = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
    user = get("https://api.twitch.tv/helix/users", heads, {"login": handle})
    data = (user.get("data") or [])
    if not data:
        return []
    uid = data[0].get("id", "")
    start = (_dt.datetime.now(_dt.timezone.utc)
             - _dt.timedelta(days=max(1, days))).isoformat(timespec="seconds")
    res = get("https://api.twitch.tv/helix/clips", heads,
              {"broadcaster_id": uid, "first": min(100, max(1, first)),
               "started_at": start})
    out = []
    for c in (res.get("data") or []):
        cid = str(c.get("id") or "")
        if not cid:
            continue
        try:
            dur = float(c.get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        try:
            off = c.get("vod_offset")
            off = float(off) if off is not None else -1.0
        except (TypeError, ValueError):
            off = -1.0
        out.append({
            "clip_id": cid, "streamer": handle,
            "url": str(c.get("url") or f"https://clips.twitch.tv/{cid}"),
            "titulo_clip": str(c.get("title") or "")[:150],
            "duracao": dur,
            "views": int(c.get("view_count") or 0),
            "created_at": str(c.get("created_at") or ""),
            "vod_id": str(c.get("video_id") or ""),
            "vod_offset": off,
        })
    return out


def is_clip_duplicate(con, clip: dict, tol: float = OFFSET_TOL) -> bool:
    """True se clip_id exato OU mesmo momento (vod+offset±tol) já visto."""
    row = con.execute(
        "SELECT 1 FROM clips_vistos WHERE clip_id=?", (clip.get("clip_id"),)
    ).fetchone()
    if row:
        return True
    vod, off = str(clip.get("vod_id") or ""), float(clip.get("vod_offset") or -1)
    if vod and off >= 0:
        rows = con.execute(
            "SELECT vod_offset FROM clips_vistos WHERE vod_id=?", (vod,)
        ).fetchall()
        if any(abs(float(r["vod_offset"]) - off) <= tol for r in rows):
            return True
    return False


def register_clip(con, clip: dict) -> None:
    con.execute(
        "INSERT OR IGNORE INTO clips_vistos"
        "(clip_id, streamer, vod_id, vod_offset, views, titulo, visto_em)"
        " VALUES(?,?,?,?,?,?,?)",
        (clip.get("clip_id"), clip.get("streamer"), str(clip.get("vod_id") or ""),
         float(clip.get("vod_offset") or -1), int(clip.get("views") or 0),
         str(clip.get("titulo_clip") or "")[:150],
         _dt.date.today().isoformat()),
    )


def discover_clips(day: str, db_path: Path, factory_data: Path,
                   max_clips_dia: int = 5, min_views: int = 50,
                   min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
                   fetch_fn=None) -> list[dict]:
    """Roda sozinho: whitelist Twitch -> clips novos -> data/<dia>/clips.json.

    Filtra duração/views/dedup, ordena por views, registra SÓ os escolhidos
    como vistos (backlog não escolhido sobrevive p/ próximos dias).
    """
    _db.init_db(db_path)
    tw_id = os.environ.get("TWITCH_CLIENT_ID", "")
    tw_sec = os.environ.get("TWITCH_CLIENT_SECRET", "")
    fetch = fetch_fn or (lambda h: fetch_clips(h, tw_id, tw_sec))
    whitelist = [s for s in _disc.load_whitelist(db_path)
                 if s["plataforma"] == "twitch"]
    con = _db.connect(db_path)
    try:
        novos: list[dict] = []
        for s in whitelist:
            try:
                clips = fetch(s["handle"]) or []
            except Exception:
                continue
            for c in clips:
                if not (min_dur <= float(c.get("duracao") or 0) <= max_dur):
                    continue
                if int(c.get("views") or 0) < min_views:
                    continue
                if is_clip_duplicate(con, c):
                    continue
                novos.append(c)
        novos.sort(key=lambda c: int(c.get("views") or 0), reverse=True)
        escolhidos = novos[:max(0, max_clips_dia)]
        # Só os escolhidos viram "vistos": o resto do backlog sobrevive
        # para os próximos dias; o escolhido nunca mais volta.
        for c in escolhidos:
            register_clip(con, c)
        con.commit()
    finally:
        con.close()
    day_dir = factory_data / day
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "clips.json").write_text(
        json.dumps(escolhidos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"clips: {len(escolhidos)} novo(s) em {day} "
          f"({len(novos)} vistos-no-dia, resto já era repetido/filtro)")
    return escolhidos


def main(day: str, db_path: Path, factory_data: Path) -> int:
    discover_clips(day, db_path, factory_data)
    return 0
