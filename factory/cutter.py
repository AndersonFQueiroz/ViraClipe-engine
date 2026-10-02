"""Corte vertical 9:16 dos scored -> data/<dia>/corte-<cut_id>.mp4.

Layout split (gameplay topo + facecam base) quando há rosto; senão
crop central. h264/aac + faststart, 1 passo ffmpeg.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import db as _db
from . import reframe as _rf

OUT_W, OUT_H = 720, 1280


def cut_cmd(mp4_in: Path, t_inicio: float, duracao: float, out_mp4: Path,
            face_box: tuple[int, int, int, int] | None = None) -> list[str]:
    split = _rf.split_filter(face_box) if face_box else None
    vf = split or f"crop=ih*9/16:ih,scale={OUT_W}:{OUT_H}"
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
              runner=subprocess.run,
              face_box: tuple[int, int, int, int] | None = None) -> bool:
    try:
        r = runner(cut_cmd(mp4_in, t_inicio, duracao, out_mp4, face_box),
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
                t_ini = float(s.get("t_inicio", 0))
                dur = float(s.get("duracao", s.get("t_fim", 30) - s.get("t_inicio", 0) if isinstance(s.get("t_fim"), (int, float)) else 30))
                try:
                    box = _rf.find_face_box(Path(src), t_ini, dur, runner=runner)
                except Exception:
                    box = None
                print(f"cutter: {cut_id} layout={'split' if box else 'centro'}")
                ok = cut_corte(Path(src), t_ini, dur, out, runner=runner, face_box=box)
                if not ok:
                    continue
            _chat = s.get("chat", 0)
            _chat = 0.0 if _chat is None else float(_chat)
            try:
                import json as _json
                _rub = _json.dumps(s.get("rubrica") or {}, ensure_ascii=False)[:300]
            except Exception:
                _rub = ""
            try:
                _voz = float(s.get("voz", 50))
            except (TypeError, ValueError):
                _voz = 50.0
            con.execute(
                "INSERT OR REPLACE INTO cortes(cut_id, video_id, streamer, t_inicio, duracao,"
                " chat, audio, viral, score_final, titulo, status, voz, rubrica, jogo)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cut_id, vid, str(s.get("streamer") or ""),
                 float(s.get("t_inicio", 0)), float(s.get("duracao", 30)),
                 _chat, float(s.get("audio", 0)),
                 s.get("viral"), float(s.get("score_final", 0)),
                 str(s.get("titulo") or ""), "cut", _voz, _rub,
                 str(s.get("jogo") or "")[:60]),
            )
            cortes.append({**s, "cut_id": cut_id, "mp4": str(out)})
        con.commit()
    finally:
        con.close()
    (day_dir / "cortes.json").write_text(
        json.dumps(cortes, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return cortes
