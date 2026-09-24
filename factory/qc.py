"""QC bloqueante: reprovou 1, nada é postado (exit 1).

Port do ReelIfy + regras de corte: crédito obrigatório, blocklist,
dedup (video_id+t_inicio), specs 720x1280 h264/aac faststart.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import db as _db

MIN_BYTES = 100_000


def ffprobe(path: Path, runner=subprocess.run) -> dict:
    r = runner(
        ["ffprobe", "-hide_banner", "-loglevel", "error", "-show_entries",
         "format=duration,size:stream=width,height,codec_name,codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return json.loads(r.stdout or "{}")


def check_faststart(path: Path) -> bool:
    try:
        blob = path.read_bytes()
        moov, mdat = blob.find(b"moov"), blob.find(b"mdat")
        return moov != -1 and (mdat == -1 or moov < mdat)
    except Exception:
        return False


def load_blocklist(root: Path | None = None) -> list[str]:
    base = root or Path(__file__).resolve().parent.parent
    p = base / "config" / "blocklist.txt"
    terms: list[str] = []
    if p.exists():
        terms = [
            t for line in p.read_text(encoding="utf-8").splitlines()
            for t in [line.strip().lower()]
            if t and not t.startswith("#")
        ]
        # Compat: linha única com espaços vira 1 termo; split extra vem do privado.
        flat: list[str] = []
        for t in terms:
            flat.extend([w for w in t.split() if w])
        # Mantém termos multi-palavra também (ex "endereço pessoal")
        terms = sorted(set(terms + flat))
    try:
        from config.secret_loader import get_blocklist_extra

        for t in get_blocklist_extra():
            if t not in terms:
                terms.append(t)
    except Exception:
        pass
    return terms


def check_video(key: str, path: Path, errors: list[str], runner=subprocess.run) -> None:
    if not path.exists() or path.stat().st_size < MIN_BYTES:
        errors.append(f"{key}: arquivo ausente ou minúsculo")
        return
    try:
        info = ffprobe(path, runner=runner)
    except Exception as exc:
        errors.append(f"{key}: ffprobe erro ({exc})")
        return
    dur = float((info.get("format") or {}).get("duration") or 0)
    if not 25 <= dur <= 70:
        errors.append(f"{key}: duração {dur:.1f}s fora de 25-70s")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    if (v.get("width"), v.get("height")) != (720, 1280):
        errors.append(f"{key}: resolução {v.get('width')}x{v.get('height')} ≠ 720x1280")
    if v.get("codec_name") != "h264":
        errors.append(f"{key}: vídeo {v.get('codec_name')} ≠ h264")
    if a.get("codec_name") != "aac":
        errors.append(f"{key}: áudio {a.get('codec_name')} ≠ aac")
    if not a:
        errors.append(f"{key}: sem faixa de áudio")
    if not check_faststart(path):
        errors.append(f"{key}: sem faststart (moov após mdat)")


def check_credito(corte: dict, errors: list[str]) -> None:
    texto = f"{corte.get('titulo','')} {corte.get('descricao','')}"
    if not corte.get("streamer"):
        errors.append(f"{corte.get('cut_id')}: sem streamer")
    if "@" not in texto and "twitch.tv" not in texto and "youtube.com" not in texto:
        errors.append(f"{corte.get('cut_id')}: sem crédito/link do VOD na legenda")


def check_blocklist(corte: dict, blocklist: list[str], errors: list[str]) -> None:
    texto = f"{corte.get('titulo','')} {corte.get('descricao','')} {' '.join(corte.get('hashtags') or [])}".lower()
    for b in blocklist:
        if b and b in texto:
            errors.append(f"{corte.get('cut_id')}: blocklist '{b}'")
            break


def qc_day(
    day: str, factory_data: Path, db_path: Path,
    runner=subprocess.run, blocklist: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Valida scored.json + mp4s + dedup. Retorna (ok, errors)."""
    errors: list[str] = []
    bl = blocklist if blocklist is not None else load_blocklist()
    day_dir = factory_data / day
    scored_path = day_dir / "scored.json"
    if not scored_path.exists():
        return False, ["scored.json ausente — rode score antes do QC"]
    scored = json.loads(scored_path.read_text(encoding="utf-8"))
    if not scored:
        return False, ["nada para postar (scored vazio)"]
    con = _db.connect(db_path)
    try:
        for c in scored:
            cut_id = str(c.get("cut_id") or "")
            vid = str(c.get("video_id") or "")
            try:
                t_ini = float(c.get("t_inicio", 0))
            except (TypeError, ValueError):
                t_ini = 0.0
            if _db.is_cut_duplicate(con, vid, t_ini):
                errors.append(f"{cut_id}: duplicado (video_id+t_inicio já postado)")
            check_credito(c, errors)
            check_blocklist(c, bl, errors)
            mp4 = day_dir / f"corte-{cut_id}.mp4"
            alt = c.get("mp4")
            path = mp4 if mp4.exists() else (Path(str(alt)) if alt else mp4)
            # em teste sem mp4 real, registra aviso em vez de falhar duro se marcado
            if path.exists():
                check_video(cut_id, path, errors, runner=runner)
            else:
                errors.append(f"{cut_id}: mp4 ausente ({path.name})")
    finally:
        con.close()
    return (len(errors) == 0), errors


def main(day: str, factory_data: Path, db_path: Path) -> int:
    ok, errors = qc_day(day, factory_data, db_path)
    for e in errors:
        print(f"QC FALHA: {e}")
    if not ok:
        print(f"QC: {len(errors)} falha(s) — ENVIO BLOQUEADO.")
        return 1
    print("QC OK — liberado p/ Buffer.")
    return 0
