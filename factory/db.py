"""SQLite central do ViraClipe (dedup + whitelist + agenda)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS streamers(
  handle TEXT NOT NULL,
  plataforma TEXT NOT NULL,
  cortes_liberados INTEGER NOT NULL DEFAULT 0,
  denylist INTEGER NOT NULL DEFAULT 0,
  ultimo_vod TEXT,
  PRIMARY KEY(handle, plataforma)
);
CREATE TABLE IF NOT EXISTS vods_processados(
  video_id TEXT PRIMARY KEY,
  plataforma TEXT NOT NULL,
  streamer TEXT NOT NULL,
  duracao REAL NOT NULL DEFAULT 0,
  baixado_em TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cortes(
  cut_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  streamer TEXT NOT NULL,
  t_inicio REAL NOT NULL,
  duracao REAL NOT NULL,
  chat REAL NOT NULL DEFAULT 0,
  audio REAL NOT NULL DEFAULT 0,
  viral REAL,
  score_final REAL NOT NULL DEFAULT 0,
  titulo TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'scored'
);
CREATE TABLE IF NOT EXISTS posts(
  cut_id TEXT NOT NULL,
  rede TEXT NOT NULL,
  buffer_id TEXT NOT NULL DEFAULT '',
  agendado_para TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(cut_id, rede)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def init_db(db_path: Path) -> None:
    con = connect(db_path)
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()


def is_denylisted(con: sqlite3.Connection, handle: str, plataforma: str) -> bool:
    row = con.execute(
        "SELECT denylist FROM streamers WHERE handle=? AND plataforma=?",
        (handle, plataforma),
    ).fetchone()
    return bool(row and row["denylist"])


def is_vod_processed(con: sqlite3.Connection, video_id: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM vods_processados WHERE video_id=?", (video_id,)
    ).fetchone()
    return row is not None


def is_cut_duplicate(con: sqlite3.Connection, video_id: str, t_inicio: float, tol: float = 2.0) -> bool:
    rows = con.execute(
        "SELECT t_inicio FROM cortes WHERE video_id=?", (video_id,)
    ).fetchall()
    return any(abs(float(r["t_inicio"]) - t_inicio) <= tol for r in rows)
