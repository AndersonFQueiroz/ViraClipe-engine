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
import subprocess
from pathlib import Path

from . import cutter as _cutter
from . import db as _db
from . import discovery as _disc
from . import pack_redes as _pack
from . import render as _render

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
    games: dict[str, str] = {}
    try:
        gids = sorted({str(c.get("game_id") or "") for c in (res.get("data") or [])} - {""})
        for i in range(0, len(gids), 100):
            g = get("https://api.twitch.tv/helix/games", heads,
                    {"id": gids[i:i + 100]})
            for gg in (g.get("data") or []):
                games[str(gg.get("id"))] = str(gg.get("name") or "")
    except Exception:
        games = {}
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
            "game_id": str(c.get("game_id") or ""),
            "jogo": games.get(str(c.get("game_id") or ""), ""),
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
                   max_clips_dia: int = 5, min_views: int = 10,
                   min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
                   fetch_fn=None, registrar: bool = True,
                   max_por_streamer: int = 2) -> list[dict]:
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
        # Diversifica: teto por streamer (ninguém engole os 5 slots sozinho).
        escolhidos = []
        por_streamer: dict[str, int] = {}
        for c in novos:
            if len(escolhidos) >= max(0, max_clips_dia):
                break
            s = str(c.get("streamer") or "?")
            if por_streamer.get(s, 0) >= max(1, max_por_streamer):
                continue
            por_streamer[s] = por_streamer.get(s, 0) + 1
            escolhidos.append(c)
        # Só os escolhidos viram "vistos": o resto do backlog sobrevive
        # para os próximos dias; o escolhido nunca mais volta.
        # registrar=False: marcação fica p/ depois do corte OK (não queima
        # clip cujo download falhar).
        if registrar:
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


def download_clip(clip: dict, out_mp4: Path, runner=subprocess.run) -> bool:
    """Baixa o mp4 do clip via yt-dlp (1080p quando houver)."""
    url = str(clip.get("url") or "")
    if not url:
        return False
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = runner(
            ["yt-dlp", "-f", "bv*+ba/b", "--no-playlist", "--no-warnings",
             "-o", str(out_mp4), url],
            capture_output=True, text=True, timeout=600,
        )
        return (r.returncode == 0 and out_mp4.exists()
                and out_mp4.stat().st_size > 100_000)
    except Exception:
        return False


def mark_clips_usados(db_path: Path, clips: list[dict]) -> None:
    """Registra clips como vistos APÓS corte OK (não queima falha)."""
    con = _db.connect(db_path)
    try:
        for c in clips:
            register_clip(con, c)
        con.commit()
    finally:
        con.close()


def _clip_to_scored(clip: dict, mp4: Path, legenda: dict | None = None) -> dict:
    """Adapta clip p/ formato scored.json (reuso total cutter/render/pack)."""
    cid = str(clip.get("clip_id") or "sem-id")
    dur = float(clip.get("duracao") or 30)
    views = int(clip.get("views") or 0)
    leg = legenda or {}
    streamer = str(clip.get("streamer") or "")
    jogo = str(clip.get("jogo") or "").strip()[:60]
    tags = list(leg.get("hashtags") or [])
    if jogo:
        slug = "".join(ch for ch in jogo.lower() if ch.isalnum())[:30]
        if slug and slug not in [str(t).lower() for t in tags]:
            tags = ([slug] + tags)[:5]
    return {
        "cut_id": f"clip-{cid[:32]}",
        "video_id": f"clip:{cid}",
        "streamer": streamer,
        "url": str(clip.get("url") or ""),
        "t_inicio": 0.0, "t_fim": dur, "duracao": dur,
        "chat": min(100.0, views / 10.0),  # views viram sinal 0-100
        "audio": 50.0,
        "viral": leg.get("viral_clip"),
        "motivo": leg.get("motivo", ""),
        "score_final": min(100.0, views / 10.0),
        "titulo": str(leg.get("titulo") or clip.get("titulo_clip") or "Melhor momento")[:90],
        "descricao": str(leg.get("descricao") or f"@{streamer} na Twitch 🎮"),
        "hashtags": tags,
        "jogo": jogo,
        "_mp4": str(mp4),
    }


def process_clips_day(day: str, db_path: Path, factory_data: Path,
                      max_n: int = 2, min_views: int = 10,
                      runner=subprocess.run,
                      model: str = "gemini-3.5-flash-lite", api_key: str = "",
                      gemini_fn=None, keys: list[str] | None = None) -> list[dict]:
    """Fonte A fim-a-fim até o pack: clips.json -> download -> split+marca.

    Retorna finais (finais.json + pack.json prontos p/ QC/telegram).
    """
    day_dir = factory_data / day
    clips = discover_clips(day, db_path, factory_data, max_clips_dia=max_n,
                           min_views=min_views, registrar=False)
    if not clips:
        print("clips: nada novo — fonte B (VOD) deve cobrir.")
        return []
    from . import score as _score

    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    raw = day_dir / "raw"
    scored, ingest_list, ok_clips = [], [], []
    for i, c in enumerate(clips):
        safe = "".join(x if x.isalnum() or x in "-_" else "_" for x in c["clip_id"])
        mp4 = raw / f"clip-{safe[:32]}.mp4"
        if not (mp4.exists() and mp4.stat().st_size > 100_000):
            if not download_clip(c, mp4, runner=runner):
                print(f"clips: download falhou {c['clip_id'][:20]} — pulando (não queima)")
                continue
        if i > 0:
            _score._pace()  # 1 call por corte; mesmo assim, sem rajada
        # Tom do próprio canal: títulos irmãos viram referência de humor.
        refs = [x.get("titulo_clip", "") for x in clips if x is not c]
        leg = _score.legendar_clip(c, model, key, gemini_fn=gemini_fn, refs=refs)
        print(f"clips: legenda '{leg['titulo'][:50]}' viral_clip={leg.get('viral_clip')}")
        s = _clip_to_scored(c, mp4, leg)
        scored.append(s)
        ingest_list.append({**c, "video_id": s["video_id"], "mp4": str(mp4)})
        ok_clips.append(c)
    if not scored:
        return []
    (day_dir / "scored.json").write_text(
        json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
    (day_dir / "ingest.json").write_text(
        json.dumps(ingest_list, ensure_ascii=False, indent=1), encoding="utf-8")
    cortes = _cutter.cutter_day(day, factory_data, db_path, runner=runner)
    finais = _render.render_day(day, factory_data, runner=runner)
    if finais:
        _pack.build_pack(day_dir, finais, keys=keys, db_path=db_path)
        mark_clips_usados(db_path, ok_clips)
        print(f"clips: {len(finais)} final(is) + pack pronto.")
    return finais


def main(day: str, db_path: Path, factory_data: Path) -> int:
    discover_clips(day, db_path, factory_data)
    return 0
