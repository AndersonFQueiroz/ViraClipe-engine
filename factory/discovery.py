"""Discovery pós-live: whitelist -> VODs novas -> data/<dia>/vods.json.

Sem credenciais de API retorna lista vazia (não quebra o Termux).
Funções de rede são injetáveis para testes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import db as _db

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


def fetch_twitch_vods(handle: str, client_id: str = "", client_secret: str = "") -> list[dict]:
    """Lista últimos VODs Twitch via Helix. Sem credenciais retorna []."""
    if not (client_id and client_secret):
        return []
    # Implementação real usa Helix: oauth client_credentials + /helix/videos?user_login=
    # Mantida fora do MVP para não travar sem rede; retorna [] até haver credencial válida.
    # (Não fazer request sem credencial para não gastar quota/quebrar no Termux.)
    return []


def fetch_youtube_vods(handle: str, api_key: str = "") -> list[dict]:
    """Lista VODs via playlistItems do canal. Sem chave retorna []."""
    if not api_key:
        return []
    return []


def discover(
    day: str,
    db_path: Path,
    factory_data: Path,
    max_vods_dia: int = 5,
    fetchers: dict | None = None,
) -> list[dict]:
    """Roda discovery e salva data/<dia>/vods.json. Retorna VODs novas."""
    fetchers = fetchers or {}
    twitch_fn = fetchers.get("twitch", fetch_twitch_vods)
    youtube_fn = fetchers.get("youtube", fetch_youtube_vods)
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
