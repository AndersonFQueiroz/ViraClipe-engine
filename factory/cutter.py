"""Corte vertical 9:16 dos scored -> data/<dia>/corte-<cut_id>.mp4.

ffmpeg 1 passo: seek + crop central + scale 720x1280 + h264/aac + faststart.
Sem tracking de rosto no MVP (Fase 2).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import db as _db

OUT_W, OUT_H = 720, 1280


def cut_cmd(mp4_in: Path, t_inicio: float, duracao: float, out_mp4: Path) -> list[str]:
    vf = f"crop=ih*9/16:ih,scale={OUT_W}:{OUT_H}"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{t_inicio:.1f}", "-t", f"{duracao:.1f}",
        "-i", str(mp4_in),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_mp4),
    ]


def cut_corte(mp4_in: Path, t_inicio: float, duracao: float, out_mp4: Path,
              runner=subprocess.run) -> bool:
    try:
        r = runner(cut_cmd(mp4_in, t_inicio, duracao, out_mp4),
                   capture_output=True, text=True, timeout=900)
        return r.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 100_000
    except Exception:
        return False


def cutter_day(day: str, factory_data: Path, db_path: Path, runner=subprocess.run) -> list[dict]:
    day_dir = factory_data / day
    scored = json.loads((day_dir / "scored.json").read_text(encoding="utf-8"))
    ingest = {}
    ing_path = day_dir / "ingest.json"
    if ing_path.exists():
        for v in json.loads(ing_path.read_text(encoding="utf-8")):
            ingest[str(v.get("video_id"))] = v
    cortes: list[dict] = []
    con = _db.connect(db_path)
    try:
        for s in scored:
            vid = str(s.get("video_id") or "")
            src = ingest.get(vid, {}).get("mp4", "")
            if not src or not Path(src).exists():
                continue
            cut_id = str(s.get("cut_id") or f"{vid}-{float(s.get('t_inicio', 0)):.0f}")
            out = day_dir / f"corte-{cut_id}.mp4"
            if not (out.exists() and out.stat().st_size > 100_000):
                ok = cut_corte(Path(src), float(s.get("t_inicio", 0)),
                               float(s.get("duracao", s.get("t_fim", 30) - s.get("t_inicio", 0) if isinstance(s.get("t_fim"), (int, float)) else 30)),
                               out, runner=runner)
                if not ok:
                    continue
            con.execute(
                "INSERT OR REPLACE INTO cortes(cut_id, video_id, streamer, t_inicio, duracao,"
                " chat, audio, viral, score_final, titulo, status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (cut_id, vid, str(s.get("streamer") or ""),
                 float(s.get("t_inicio", 0)), float(s.get("duracao", 30)),
                 float(s.get("chat", 0)), float(s.get("audio", 0)),
                 s.get("viral"), float(s.get("score_final", 0)),
                 str(s.get("titulo") or ""), "cut"),
            )
            cortes.append({**s, "cut_id": cut_id, "mp4": str(out)})
        con.commit()
    finally:
        con.close()
    (day_dir / "cortes.json").write_text(
        json.dumps(cortes, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return cortes
