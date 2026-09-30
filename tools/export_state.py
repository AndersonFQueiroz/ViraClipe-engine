"""Exporta estado anti-repetição p/ seed da nuvem (1x na migração).

Gera data/seed_state.sql com INSERT OR IGNORE (sem segredos: só ids,
títulos, captions, slots). A diaria aplica sempre (idempotente).
Uso: python3 tools/export_state.py [--offset N]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_PATH


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def main() -> int:
    off = ""
    if "--offset" in sys.argv:
        off = sys.argv[sys.argv.index("--offset") + 1]
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    lines = ["-- seed anti-repetição (gerado, pode commitar; sem segredos)",
             "CREATE TABLE IF NOT EXISTS cortes(cut_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, streamer TEXT NOT NULL, t_inicio REAL NOT NULL, duracao REAL NOT NULL DEFAULT 0, chat REAL NOT NULL DEFAULT 0, audio REAL NOT NULL DEFAULT 0, viral REAL, score_final REAL NOT NULL DEFAULT 0, titulo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'scored');",
             "CREATE TABLE IF NOT EXISTS clips_vistos(clip_id TEXT PRIMARY KEY, streamer TEXT NOT NULL, vod_id TEXT NOT NULL DEFAULT '', vod_offset REAL NOT NULL DEFAULT -1, views INTEGER NOT NULL DEFAULT 0, titulo TEXT NOT NULL DEFAULT '', visto_em TEXT NOT NULL DEFAULT '');",
             "CREATE TABLE IF NOT EXISTS fila(cut_id TEXT PRIMARY KEY, mp4 TEXT NOT NULL DEFAULT '', titulo TEXT NOT NULL DEFAULT '', caption TEXT NOT NULL DEFAULT '', caption_tt TEXT NOT NULL DEFAULT '', dia_alvo TEXT NOT NULL DEFAULT '', slot INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'na_fila', criado_em TEXT NOT NULL DEFAULT '');",
             "CREATE TABLE IF NOT EXISTS kv(chave TEXT PRIMARY KEY, valor TEXT NOT NULL DEFAULT '');"]
    for r in con.execute("SELECT * FROM clips_vistos"):
        d = dict(r)
        lines.append(
            f"INSERT OR IGNORE INTO clips_vistos VALUES({q(d['clip_id'])},{q(d['streamer'])},{q(d['vod_id'])},{float(d['vod_offset'])},{int(d['views'])},{q(d['titulo'])},{q(d['visto_em'])});")
    for r in con.execute("SELECT * FROM cortes"):
        d = dict(r)
        lines.append(
            "INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status)"
            f" VALUES({q(d['cut_id'])},{q(d['video_id'])},{q(d['streamer'])},{float(d['t_inicio'])},{q(d['titulo'])},{q(d['status'])});")
    for r in con.execute("SELECT * FROM fila"):
        d = dict(r)
        lines.append(
            "INSERT OR REPLACE INTO fila VALUES("
            f"{q(d['cut_id'])},{q(d['mp4'])},{q(d['titulo'])},{q(d['caption'])},{q(d['caption_tt'])},{q(d['dia_alvo'])},{int(d['slot'])},{q(d['status'])},{q(d['criado_em'])});")
    if off:
        lines.append(f"INSERT OR REPLACE INTO kv VALUES('tg_offset',{q(off)});")
    con.close()
    out = Path("data/seed_state.sql")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"seed: {len(lines) - 4} linhas em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
