"""Orquestrador diário: discovery->ingest->signals->score->cutter->render->pack->qc->telegram->buffer.

AUTO-TOTAL: publica sem aprovação. QC + threshold + denylist são a trava.
Uso: python3 -m factory.run_diaria [--date AAAA-MM-DD]
Exit: 0 ok, 1 falha/QC, 2 lock, 3 sem chave (pack pronto, post pulado).
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import sys
import time
from pathlib import Path

from config.settings import DAILY_CAP, DB_PATH, FACTORY_DATA, MAX_VODS_DIA, SCORE_THRESHOLD
from factory import cutter, db as _db, discovery, ingest, pack_redes, pack_telegram, post_buffer, qc, render, score, signals

T0 = time.time()
LOCK_NAME = "viraclipe.lock"


def log(msg: str) -> None:
    print(f"[+{time.time()-T0:6.1f}s] {msg}", flush=True)


def day_arg(argv: list[str]) -> str:
    if "--date" in argv:
        return argv[argv.index("--date") + 1]
    if argv and len(argv[0]) == 10 and argv[0][4] == "-":
        return argv[0]
    return _dt.date.today().isoformat()


def main(argv: list[str]) -> int:
    day = day_arg(argv)
    FACTORY_DATA.mkdir(parents=True, exist_ok=True)
    _db.init_db(DB_PATH)
    try:
        fh = open(FACTORY_DATA / LOCK_NAME, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("ViraClipe já em execução (lock) — saindo.", file=sys.stderr)
        return 2
    log(f"ViraClipe — {day}")
    import os as _os
    model = _os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    api_key = _os.environ.get("GEMINI_API_KEY", "")

    discovery.main(day, DB_PATH, FACTORY_DATA, MAX_VODS_DIA)
    prontos = ingest.ingest_day(day, DB_PATH, FACTORY_DATA)
    if not prontos:
        log("Nenhuma VOD pronta — fim.")
        return 0
    cands = signals.signals_day(day, FACTORY_DATA)
    log(f"Candidatos: {len(cands)}")
    if not cands:
        return 0
    sel = score.score_day(day, FACTORY_DATA, model, api_key, float(SCORE_THRESHOLD), int(DAILY_CAP))
    log(f"Selecionados (>={SCORE_THRESHOLD}): {len(sel)}")
    if not sel:
        return 0
    cortes = cutter.cutter_day(day, FACTORY_DATA, DB_PATH)
    finais = render.render_day(day, FACTORY_DATA)
    if not finais:
        log("FALHA: nenhum corte renderizado.")
        return 1
    pack_redes.build_pack(FACTORY_DATA / day, finais)
    log("Pack pronto.")
    if qc.main(day, FACTORY_DATA, DB_PATH) != 0:
        log("QC FALHOU — nada enviado.")
        return 1
    rc_tg = pack_telegram.main(day, FACTORY_DATA)
    # Marca cortes como postados (dedup futuro) antes do Buffer
    con = _db.connect(DB_PATH)
    try:
        for c in json.loads((FACTORY_DATA / day / "finais.json").read_text(encoding="utf-8")):
            con.execute("UPDATE cortes SET status='qc_ok' WHERE cut_id=?", (c["cut_id"],))
        con.commit()
    finally:
        con.close()
    rc_buf = post_buffer.main(day, FACTORY_DATA)
    log(f"FIM tg={rc_tg} buffer={rc_buf}")
    # limpa raws para não lotar o Termux
    for v in prontos:
        try:
            Path(v["mp4"]).unlink(missing_ok=True)
        except Exception:
            pass
    return 0 if rc_buf in (0, 3) else rc_buf


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
