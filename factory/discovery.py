"""Discovery pós-live: whitelist -> VODs novas -> data/<dia>/vods.json.

Sem credenciais de API retorna lista vazia (não quebra o Termux).
Funções de rede são injetáveis para testes.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

from . import db as _db
from . import net as _net

PERMISSAO_RE = re.compile(
    r"cortes?\s+liberados?|pode\s+clipar|clipes?\s+liberados?|"
    r"pode\s+postar\s+cortes?|free\s+clips?",
    re.IGNORECASE,
)


def tem_permissao(texto: str) -> bool:
    """Triagem 'cortes liberados' na bio/descrição (tools/check_permissao usa esta fn)."""
    return bool(PERMISSAO_RE.search(texto or ""))


def load_whitelist(db_path: Path) -> list[dict]:
    con = _db.connect(db_path)
    try:
        rows = con.execute(
            "SELECT handle, plataforma FROM streamers "
            "WHERE cortes_liberados=1 AND denylist=0"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def filter_new_vods(
    vods: list[dict],
    processed_ids: set[str],
    max_vods_dia: int,
) -> list[dict]:
    novos = [v for v in vods if v.get("video_id") not in processed_ids]
    # ordena por viewers (se houver) para priorizar em alta
    novos.sort(key=lambda v: float(v.get("viewers") or 0), reverse=True)
    return novos[:max(0, max_vods_dia)]


_TWITCH_TOKEN: str = ""


def _twitch_token(client_id: str, client_secret: str, http_post=None) -> str:
    """App token client_credentials (cache em memória). Levanta em falha."""
    global _TWITCH_TOKEN
    if _TWITCH_TOKEN:
        return _TWITCH_TOKEN
    post = http_post or (lambda url, data, timeout: _net.post(requests.Session(), url, data=data, timeout=timeout))
    r = post("https://id.twitch.tv/oauth2/token",
             {"client_id": client_id, "client_secret": client_secret,
              "grant_type": "client_credentials"}, 30)
    token = (r.json() if hasattr(r, "json") else r).get("access_token", "")
    if not token:
        raise RuntimeError("twitch oauth sem access_token")
    _TWITCH_TOKEN = token
    return token


def _twitch_dur(text: str) -> float:
    """'2h15m30s' -> segundos."""
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", (text or "").strip())
    if not m or not any(m.groups()):
        return 0.0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return float(h * 3600 + mi * 60 + s)


def _yt_dur(text: str) -> float:
    """ISO8601 'PT1H2M3S' -> segundos."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", (text or "").strip())
    if not m or not any(m.groups()):
        return 0.0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return float(h * 3600 + mi * 60 + s)


def _http_get(url: str, headers: dict | None = None, params: dict | None = None, timeout: int = 30) -> dict:
    def _do():
        r = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()

    return _net.call(_do)


def fetch_twitch_vods(handle: str, client_id: str = "", client_secret: str = "",
                      http_get=None, http_post=None) -> list[dict]:
    """Últimos VODs (archive) via Helix. Sem credenciais retorna []."""
    if not (client_id and client_secret):
        return []
    get = http_get or _http_get
    token = _twitch_token(client_id, client_secret, http_post)
    heads = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
    user = get("https://api.twitch.tv/helix/users", heads, {"login": handle})
    data = (user.get("data") or [])
    if not data:
        return []
    uid = data[0].get("id", "")
    vods = get("https://api.twitch.tv/helix/videos", heads,
               {"user_id": uid, "first": 5, "type": "archive"})
    out = []
    for v in (vods.get("data") or []):
        vid = str(v.get("id") or "")
        if not vid:
            continue
        out.append({
            "video_id": f"twitch:{vid}", "plataforma": "twitch", "streamer": handle,
            "url": str(v.get("url") or f"https://www.twitch.tv/videos/{vid}"),
            "titulo_vod": str(v.get("title") or "")[:120],
            "duracao": _twitch_dur(str(v.get("duration") or "")),
            "viewers": int(v.get("view_count") or 0),
            "published_at": str(v.get("published_at") or ""),
        })
    return out


def _yt_channel_id(handle: str, api_key: str, get) -> str:
    h = (handle or "").strip().lstrip("@")
    if re.fullmatch(r"UC[\w-]{22}", handle.strip()):
        return handle.strip()
    if h.startswith("@") or not h.startswith("UC"):
        name = h[1:] if h.startswith("@") else h
        res = get("https://www.googleapis.com/youtube/v3/channels",
                  None, {"part": "contentDetails", "forHandle": f"@{name}", "key": api_key})
        items = res.get("items") or []
        if items:
            return str(items[0].get("id") or "")
        # fallback: forUsername legado
        res = get("https://www.googleapis.com/youtube/v3/channels",
                  None, {"part": "contentDetails", "forUsername": name, "key": api_key})
        items = res.get("items") or []
        if items:
            return str(items[0].get("id") or "")
        return ""
    return h


def fetch_youtube_vods(handle: str, api_key: str = "", http_get=None) -> list[dict]:
    """VODs via uploads playlist (1 un/chamada, sem search de 100 un). Sem chave retorna []."""
    if not api_key:
        return []
    get = http_get or _http_get
    cid = _yt_channel_id(handle, api_key, get)
    if not cid:
        return []
    ch = get("https://www.googleapis.com/youtube/v3/channels",
             None, {"part": "contentDetails", "id": cid, "key": api_key})
    items = ch.get("items") or []
    if not items:
        return []
    uploads = (((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {})
               .get("uploads") or "")
    if not uploads:
        return []
    pl = get("https://www.googleapis.com/youtube/v3/playlistItems",
             None, {"part": "contentDetails", "playlistId": uploads,
                    "maxResults": 5, "key": api_key})
    vids = [str((it.get("contentDetails") or {}).get("videoId") or "")
            for it in (pl.get("items") or [])]
    vids = [v for v in vids if v]
    if not vids:
        return []
    det = get("https://www.googleapis.com/youtube/v3/videos",
              None, {"part": "snippet,contentDetails,statistics",
                     "id": ",".join(vids), "key": api_key})
    out = []
    for v in (det.get("items") or []):
        vid = str(v.get("id") or "")
        sn, cd, st = v.get("snippet") or {}, v.get("contentDetails") or {}, v.get("statistics") or {}
        out.append({
            "video_id": f"youtube:{vid}", "plataforma": "youtube", "streamer": handle,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "titulo_vod": str(sn.get("title") or "")[:120],
            "duracao": _yt_dur(str(cd.get("duration") or "")),
            "viewers": int(st.get("viewCount") or 0),
            "published_at": str(sn.get("publishedAt") or ""),
        })
    return out


def discover(
    day: str,
    db_path: Path,
    factory_data: Path,
    max_vods_dia: int = 5,
    fetchers: dict | None = None,
) -> list[dict]:
    """Roda discovery e salva data/<dia>/vods.json. Retorna VODs novas."""
    fetchers = fetchers or {}
    tw_id = os.environ.get("TWITCH_CLIENT_ID", "")
    tw_sec = os.environ.get("TWITCH_CLIENT_SECRET", "")
    yt_key = os.environ.get("YOUTUBE_API_KEY", "")
    twitch_fn = fetchers.get("twitch") or (lambda h: fetch_twitch_vods(h, tw_id, tw_sec))
    youtube_fn = fetchers.get("youtube") or (lambda h: fetch_youtube_vods(h, yt_key))
    kick_fn = fetchers.get("kick", lambda handle: [])

    whitelist = load_whitelist(db_path)
    con = _db.connect(db_path)
    try:
        processed = {
            r["video_id"]
            for r in con.execute("SELECT video_id FROM vods_processados").fetchall()
        }
    finally:
        con.close()

    vods: list[dict] = []
    for s in whitelist:
        handle, plat = s["handle"], s["plataforma"]
        try:
            if plat == "twitch":
                vods.extend(twitch_fn(handle) or [])
            elif plat == "youtube":
                vods.extend(youtube_fn(handle) or [])
            elif plat == "kick":
                vods.extend(kick_fn(handle) or [])
        except Exception:
            continue

    novos = filter_new_vods(vods, processed, max_vods_dia)
    day_dir = factory_data / day
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "vods.json").write_text(
        json.dumps(novos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return novos


def main(day: str, db_path: Path, factory_data: Path, max_vods_dia: int = 5) -> int:
    novos = discover(day, db_path, factory_data, max_vods_dia)
    print(f"Discovery: {len(novos)} VOD(s) nova(s) em {day}")
    return 0
