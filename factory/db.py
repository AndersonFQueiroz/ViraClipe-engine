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
CREATE TABLE IF NOT EXISTS feedback_views(
  cut_id TEXT NOT NULL,
  rede TEXT NOT NULL,
  video_id TEXT NOT NULL DEFAULT '',
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  coletado_em TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(cut_id, rede)
);
CREATE TABLE IF NOT EXISTS fila(
  cut_id TEXT PRIMARY KEY,
  mp4 TEXT NOT NULL DEFAULT '',
  titulo TEXT NOT NULL DEFAULT '',
  caption TEXT NOT NULL DEFAULT '',
  caption_tt TEXT NOT NULL DEFAULT '',
  dia_alvo TEXT NOT NULL DEFAULT '',
  slot INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'na_fila',
  criado_em TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kv(
  chave TEXT PRIMARY KEY,
  valor TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pesos_learned(
  chave TEXT PRIMARY KEY,
  valor REAL NOT NULL,
  amostras INTEGER NOT NULL DEFAULT 0,
  atualizado_em TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS clips_vistos(
  clip_id TEXT PRIMARY KEY,
  streamer TEXT NOT NULL,
  vod_id TEXT NOT NULL DEFAULT '',
  vod_offset REAL NOT NULL DEFAULT -1,
  views INTEGER NOT NULL DEFAULT 0,
  titulo TEXT NOT NULL DEFAULT '',
  visto_em TEXT NOT NULL DEFAULT ''
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
        # Migração leve: colunas da fonte B em bancos antigos (ignora se já há).
        for ddl in ("ALTER TABLE cortes ADD COLUMN voz REAL NOT NULL DEFAULT 50",
                    "ALTER TABLE cortes ADD COLUMN rubrica TEXT NOT NULL DEFAULT ''"):
            try:
                con.execute(ddl)
            except Exception:
                pass
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
    # Ignora linhas 'cut' (em progresso da rodada atual, inseridas pelo cutter
    # minutos antes do QC). Só é duplicado o que já passou do QC/post.
    rows = con.execute(
        "SELECT t_inicio FROM cortes WHERE video_id=? AND status != 'cut'", (video_id,)
    ).fetchall()
    return any(abs(float(r["t_inicio"]) - t_inicio) <= tol for r in rows)
