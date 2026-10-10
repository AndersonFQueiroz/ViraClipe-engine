"""Pack por rede: legenda + 1º comentário + título + zip Kwai (port ReelIfy).

Entrada: data/<dia>/finais.json (cortes com titulo/descricao/hashtags/url).
Saída: data/<dia>/pack.json + data/<dia>/pack_kwai.zip
Chaves dinâmicas c1..c5 (até DAILY_CAP) nos slots 9/12/15/18/21 BRT.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from config.secret_loader import get_cta, get_handle, get_tags_base

# Defaults públicos capados — full via VIRACLIP_PACK_JSON / VIRACLIP_TAGS / VIRACLIP_CTA_*.
TAGS_BASE = ["cortes", "clipes", "livetwitch", "melhoresmomentos", "viral"]
CTA = {
    "youtube": "Link da live original na descrição 👆",
    "instagram": "Live completa no link da VOD 👇",
    "tiktok": "Segue pra mais 👇",
    "kwai": "Segue pra mais cortes 👇",
}
HANDLE = "@viraclipe.oficial"


def _live_tags() -> list[str]:
    return get_tags_base()


def _live_cta() -> dict:
    return get_cta()


def _live_handle() -> str:
    return get_handle()


def _espelhar_previews(db_path: Path, dia: str, finais: list[dict], pack: dict) -> None:
    """Espelha cortes+mp4 no banco (bot aprova/edita sem arquivos)."""
    import datetime as _dt
    import sqlite3 as _sq

    try:
        con = _sq.connect(str(db_path))
        con.row_factory = _sq.Row
    except Exception:
        return
    try:
        for key, vpath in (pack.get("videos") or {}).items():
            cred = (pack.get("creditos") or {}).get(key) or {}
            cid = str(cred.get("cut_id") or "")
            if not cid:
                continue
            corte = next((c for c in finais if str(c.get("cut_id")) == cid), {})
            blob = None
            try:
                b = Path(str(vpath)).read_bytes()
                blob = b if len(b) > 100_000 else None
            except Exception:
                blob = None
            tags = corte.get("hashtags") or []
            con.execute(
                "INSERT OR REPLACE INTO previews(cut_id, dia, streamer, titulo, descricao,"
                " hashtags, caption, caption_tt, url, jogo, mp4, criado_em)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, dia, str(corte.get("streamer") or ""),
                 str(corte.get("titulo") or "")[:90],
                 str(corte.get("descricao") or "")[:500],
                 " ".join(str(t) for t in tags)[:200],
                 str((pack.get("captions") or {}).get(key) or "")[:2100],
                 str((pack.get("captions_tt") or {}).get(key) or "")[:2100],
                 str(corte.get("url") or "")[:300],
                 str(corte.get("jogo") or "")[:60],
                 blob, _dt.date.today().isoformat()))
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass


def prune_previews(db_path: Path, manter_dias: int = 3) -> int:
    """Apaga blobs mp4 antigos (metadados ficam). Banco do cache não explode."""
    import datetime as _dt
    import sqlite3 as _sq

    try:
        corte = (_dt.date.today() - _dt.timedelta(days=max(1, manter_dias))).isoformat()
        con = _sq.connect(str(db_path))
        try:
            cur = con.execute("UPDATE previews SET mp4=NULL WHERE dia < ?", (corte,))
            con.commit()
            return cur.rowcount
        finally:
            try:
                con.close()
            except Exception:
                pass
    except Exception:
        return 0


def caption_for(corte: dict, network: str = "instagram") -> tuple[str, str]:
    """Caption = só o título (regra do dono 10/10: sem descrição IA).

    Título de clip = original da Twitch (na maioria já é bom); VOD = IA/dono.
    Hashtags/handle/desc continuam no banco, fora do texto publicado.
    """
    _ = network  # formato único p/ IG/TT/YT
    handle = _live_handle()
    streamer = str(corte.get("streamer") or "")
    titulo = str(corte.get("titulo") or "Melhor momento")[:90]
    first = f"Créditos: @{streamer}\nSegue {handle} pra mais!"
    return titulo, first


def build_pack(day_dir: Path, finais: list[dict],
               keys: list[str] | None = None, db_path: Path | None = None) -> Path:
    """Monta pack.json. keys força chaves (slots livres); default c1..c5.
    Com db_path, espelha tudo na tabela previews (fonte única p/ bot/fila)."""
    captions, firsts, titles, videos, captions_tt = {}, {}, {}, {}, {}
    want = keys or [f"c{i}" for i in range(1, 6)]
    for key, c in zip(want, finais[:5]):
        if not key:
            continue
        cap, first = caption_for(c, "instagram")
        cap_tt, _ = caption_for(c, "tiktok")
        captions[key], firsts[key], captions_tt[key] = cap, first, cap_tt
        titles[key] = f"@{c.get('streamer','')} — {str(c.get('titulo',''))[:60]}"[:95]
        videos[key] = str(c["mp4"])
    cta = _live_cta()
    pack = {
        "day": day_dir.name,
        "captions": captions, "captions_tt": captions_tt,
        "first_comments": firsts, "titles": titles, "cta": cta,
        "videos": videos,
        "creditos": {k: {"streamer": finais[i].get("streamer"), "url": finais[i].get("url"),
                         "cut_id": finais[i].get("cut_id")}
                     for i, k in enumerate(videos)},
    }
    (day_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    if db_path is not None:
        _espelhar_previews(db_path, day_dir.name, finais, pack)
    zpath = day_dir / "pack_kwai.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for key, vpath in videos.items():
            z.write(vpath, Path(vpath).name)
            txt = pack["captions"][key] + "\n" + cta.get("kwai", "")
            z.writestr(f"{key}-legenda.txt", txt)
    return day_dir / "pack.json"
