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
HANDLE = "@ViraClipe"


def _live_tags() -> list[str]:
    return get_tags_base()


def _live_cta() -> dict:
    return get_cta()


def _live_handle() -> str:
    return get_handle()


def caption_for(corte: dict, network: str = "instagram") -> tuple[str, str]:
    tags_base = _live_tags()
    cta = _live_cta()
    handle = _live_handle()
    titulo = str(corte.get("titulo") or "Melhor momento")[:90]
    streamer = str(corte.get("streamer") or "")
    url = str(corte.get("url") or "")
    desc = str(corte.get("descricao") or "")
    tags = [str(t).lstrip("#") for t in (corte.get("hashtags") or [])][:4]
    if network == "tiktok":
        head = f"{titulo}"
        body = f"@{streamer} 🔥" if streamer else ""
        tail = " ".join(f"#{t}" for t in (tags or tags_base[:3]))
        cap = f"{head}\n{body}\n{tail}\n{handle}"
    else:
        lines = [f"🔥 {titulo}", f"🎮 @{streamer}" if streamer else "", desc]
        if url:
            lines.append(f"📺 Live original: {url}")
        lines.append(" ".join(f"#{t}" for t in (tags or tags_base)))
        lines.append(handle)
        cap = "\n".join(l for l in lines if l)
    first = f"Live original aqui: {url}\nCréditos: @{streamer}\nSegue {handle} pra mais!" if url else f"Créditos: @{streamer}"
    return cap, first


def build_pack(day_dir: Path, finais: list[dict]) -> Path:
    captions, firsts, titles, videos, captions_tt = {}, {}, {}, {}, {}
    for i, c in enumerate(finais[:5], 1):
        key = f"c{i}"
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
    zpath = day_dir / "pack_kwai.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for key, vpath in videos.items():
            z.write(vpath, Path(vpath).name)
            txt = pack["captions"][key] + "\n" + cta.get("kwai", "") + f"\n\nVOD: {pack['creditos'][key]['url']}"
            z.writestr(f"{key}-legenda.txt", txt)
    return day_dir / "pack.json"
