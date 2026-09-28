"""Feedback loop: views reais dos cortes -> pesos aprendidos.

1. coletar: YouTube Data API (1 unidade/quota por chamada) lê views/likes
   dos vídeos do canal e casa com cortes pelo título.
2. aprender: correlação de Pearson (sinal × views) com >=MIN_AMOSTRAS;
   mistura 50/50 com os defaults (anti-overfit de amostra pequena).
3. aplicar: escreve data/pesos_aprendidos.json (local, gitignored) que
   secret_loader usa como default; env explícito sempre vence.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
from pathlib import Path

import requests

from . import db as _db
from . import net as _net

MIN_AMOSTRAS = 5
BLEND = 0.5  # peso do aprendido vs default (amostra pequena: conservador)

SIGNALS = ("chat", "audio", "viral")
DEFAULTS = {"chat": 1 / 3, "audio": 1 / 3, "viral": 1 / 3}


def _yt_get(url: str, params: dict, timeout: int = 30) -> dict:
    def _do():
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()

    return _net.call(_do)


def fetch_channel_videos(api_key: str, channel_id: str,
                         max_videos: int = 50) -> list[dict]:
    """Vídeos do canal (uploads playlist) com views/likes. Custo ~3 unidades."""
    ch = _yt_get("https://www.googleapis.com/youtube/v3/channels",
                 {"part": "contentDetails", "id": channel_id, "key": api_key})
    items = (ch.get("items") or [])
    if not items:
        return []
    uploads = ((((items[0].get("contentDetails") or {})
                 .get("relatedPlaylists") or {}).get("uploads")) or "")
    if not uploads:
        return []
    out, token = [], ""
    while len(out) < max_videos:
        pl = _yt_get("https://www.googleapis.com/youtube/v3/playlistItems",
                     {"part": "contentDetails", "playlistId": uploads,
                      "maxResults": 50, "pageToken": token, "key": api_key})
        vids = [str((it.get("contentDetails") or {}).get("videoId") or "")
                for it in (pl.get("items") or [])]
        vids = [v for v in vids if v]
        if not vids:
            break
        for i in range(0, len(vids), 50):
            det = _yt_get("https://www.googleapis.com/youtube/v3/videos",
                          {"part": "snippet,statistics",
                           "id": ",".join(vids[i:i + 50]), "key": api_key})
            for v in (det.get("items") or []):
                sn, st = v.get("snippet") or {}, v.get("statistics") or {}
                out.append({
                    "video_id": str(v.get("id") or ""),
                    "titulo": str(sn.get("title") or ""),
                    "descricao": str(sn.get("description") or ""),
                    "views": int(st.get("viewCount") or 0),
                    "likes": int(st.get("likeCount") or 0),
                    "published_at": str(sn.get("publishedAt") or ""),
                })
        token = str(pl.get("nextPageToken") or "")
        if not token:
            break
    return out[:max_videos]


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def match_cuts(db_path: Path, videos: list[dict]) -> list[dict]:
    """Casa vídeos com cortes pelo título; grava feedback_views. Retorna matches."""
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        cuts = [dict(r) for r in con.execute(
            "SELECT cut_id, titulo FROM cortes WHERE status IN "
            "('agendado','qc_ok','cut')").fetchall()]
        matches = []
        for c in cuts:
            t = _norm(str(c.get("titulo") or ""))
            if len(t) < 6:
                continue
            for v in videos:
                hay = _norm(v.get("titulo", "") + " " + v.get("descricao", ""))
                if t and t in hay:
                    con.execute(
                        "INSERT OR REPLACE INTO feedback_views"
                        "(cut_id, rede, video_id, views, likes, coletado_em)"
                        " VALUES(?,?,?,?,?,?)",
                        (c["cut_id"], "youtube", v["video_id"], v["views"],
                         v["likes"], _dt.date.today().isoformat()))
                    matches.append({"cut_id": c["cut_id"], **v})
                    break
        con.commit()
        return matches
    finally:
        con.close()


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def learn(db_path: Path, min_amostras: int = MIN_AMOSTRAS) -> dict:
    """Correlação sinal×views -> pesos sugeridos. {} se amostra curta."""
    con = _db.connect(db_path)
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT c.chat, c.audio, c.viral, f.views FROM feedback_views f "
            "JOIN cortes c ON c.cut_id = f.cut_id WHERE f.views > 0").fetchall()]
    finally:
        con.close()
    if len(rows) < min_amostras:
        return {"ok": False, "amostras": len(rows), "min": min_amostras}
    views = [math.log1p(float(r["views"])) for r in rows]
    corrs = {}
    for s in SIGNALS:
        xs = [float(r[s]) if r[s] is not None else 50.0 for r in rows]
        corrs[s] = max(0.0, _pearson(xs, views))
    tot = sum(corrs.values())
    learned = ({s: c / tot for s, c in corrs.items()} if tot > 0
               else dict(DEFAULTS))
    blended = {s: round(BLEND * learned[s] + (1 - BLEND) * DEFAULTS[s], 3)
               for s in SIGNALS}
    return {"ok": True, "amostras": len(rows), "correlacoes":
            {s: round(corrs[s], 3) for s in SIGNALS}, "pesos": blended}


def apply_learned(factory_data: Path, pesos: dict, db_path: Path,
                  amostras: int) -> Path:
    """Escreve pesos no formato que secret_loader lê + registra no banco."""
    mapping = {"chat": ("SCORE_W_CHAT", "SIGNAL_W_CHAT"),
               "audio": ("SCORE_W_AUDIO", "SIGNAL_W_AUDIO"),
               "viral": ("SCORE_W_LLM", None)}
    out = {}
    for s, v in pesos.items():
        for key in mapping.get(s, ()):
            if key:
                out[key] = v
    p = Path(os.environ.get("PESOS_LEARNED_FILE", "data/pesos_aprendidos.json"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**out, "_amostras": amostras,
                             "_em": _dt.date.today().isoformat()},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    con = _db.connect(db_path)
    try:
        for k, v in out.items():
            con.execute(
                "INSERT OR REPLACE INTO pesos_learned(chave, valor, amostras, atualizado_em)"
                " VALUES(?,?,?,?)",
                (k, float(v), amostras, _dt.date.today().isoformat()))
        con.commit()
    finally:
        con.close()
    return p


def coletar(channel_id: str, db_path: Path, api_key: str = "",
            max_videos: int = 50) -> list[dict]:
    key = api_key or os.environ.get("YOUTUBE_API_KEY", "")
    if not (key and channel_id):
        return []
    return match_cuts(db_path, fetch_channel_videos(key, channel_id, max_videos))
