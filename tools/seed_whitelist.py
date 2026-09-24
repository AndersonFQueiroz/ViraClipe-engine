"""Seed da whitelist a partir de data/whitelist_seed.csv.

IMPORTANTE: o CSV lista CANDIDATOS, não permissões confirmadas.
O seed insere todos com cortes_liberados=0. Ative um por um APÓS
verificar bio/descrição/painel com tools/check_permissao.py:

  python3 -m tools.seed_whitelist --seed
  python3 -m tools.check_permissao "bio copiada aqui"
  python3 -m tools.seed_whitelist --activate alanzoka twitch
  python3 -m tools.seed_whitelist --list
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from factory import db as _db
from config.settings import DB_PATH

SEED = Path(__file__).resolve().parent.parent / "data" / "whitelist_seed.csv"


def seed(db_path: Path = DB_PATH, csv_path: Path = SEED) -> int:
    _db.init_db(db_path)
    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    con = _db.connect(db_path)
    try:
        n = 0
        for r in rows:
            h, p = (r.get("handle") or "").strip(), (r.get("plataforma") or "").strip()
            if not h or not p:
                continue
            cur = con.execute("SELECT cortes_liberados FROM streamers WHERE handle=? AND plataforma=?", (h, p)).fetchone()
            if cur is None:
                con.execute("INSERT INTO streamers(handle, plataforma, cortes_liberados, denylist) VALUES(?,?,0,0)", (h, p))
                n += 1
        con.commit()
    finally:
        con.close()
    print(f"Seed: {n} candidato(s) novo(s) com cortes_liberados=0. Verifique e ative com --activate.")
    return 0


def activate(handle: str, plataforma: str, db_path: Path = DB_PATH) -> int:
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        row = con.execute("SELECT denylist FROM streamers WHERE handle=? AND plataforma=?", (handle, plataforma)).fetchone()
        if row and row["denylist"]:
            print(f"{handle}/{plataforma} está na DENYLIST — não ativado.")
            return 1
        con.execute(
            "INSERT INTO streamers(handle, plataforma, cortes_liberados, denylist) VALUES(?,?,1,0)"
            " ON CONFLICT(handle, plataforma) DO UPDATE SET cortes_liberados=1",
            (handle, plataforma),
        )
        con.commit()
    finally:
        con.close()
    print(f"Ativado: {handle}/{plataforma} (cortes_liberados=1).")
    return 0


def list_all(db_path: Path = DB_PATH) -> int:
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        for r in con.execute("SELECT handle, plataforma, cortes_liberados, denylist FROM streamers ORDER BY plataforma, handle"):
            flag = "DENY" if r["denylist"] else ("ON" if r["cortes_liberados"] else "pendente")
            print(f"{r['handle']}/{r['plataforma']}: {flag}")
    finally:
        con.close()
    return 0


def main(argv: list[str]) -> int:
    if "--activate" in argv:
        i = argv.index("--activate")
        return activate(argv[i + 1], argv[i + 2])
    if "--list" in argv:
        return list_all()
    return seed()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
