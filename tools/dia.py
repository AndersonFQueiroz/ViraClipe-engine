"""Dia completo: fonte A (clips) -> se secar, fonte B (VOD) -> QC -> prévias.

Nada agenda sozinho: tudo termina em ✅/❌ no Telegram (gate humano).
Uso: python3 tools/dia.py [--date AAAA-MM-DD] [--max 2] [--fonte auto|a|b]
Exit: 0 prévias enviadas (ou nada novo), 1 QC falhou.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_PATH, FACTORY_DATA
from factory import (aprova, clips, cutter, discovery, ingest, pack_redes,
                     qc, render, score, signals, transcribe)

T0 = time.time()


def log(msg: str) -> None:
    print(f"[+{time.time()-T0:6.1f}s] {msg}", flush=True)


def _finalizar(day: str, finais: list[dict]) -> int:
    if not finais:
        return 0
    if qc.main(day, FACTORY_DATA, DB_PATH) != 0:
        log("QC FALHOU — nada enviado.")
        return 1
    aprova.marcar_qc_ok(DB_PATH, [str(f.get("cut_id")) for f in finais])
    res = aprova.enviar_previews(day, FACTORY_DATA, DB_PATH)
    log(f"prévias {res} — aguardando ✅/❌ no Telegram.")
    return 0 if res.get("ok") else 1


def fonte_a(day: str, max_n: int) -> list[dict]:
    log("fonte A: clips da comunidade...")
    return clips.process_clips_day(day, DB_PATH, FACTORY_DATA, max_n=max_n)


def fonte_b(day: str, max_vods: int = 1) -> list[dict]:
    log("fonte B: VOD (phase-1+2 melhorado)...")
    model = os.environ.get("GEMINI_MODEL", "") or "gemini-3.6-flash"
    score_model = os.environ.get("SCORE_MODEL", "") or "gemini-3.5-flash-lite"
    api_key = os.environ.get("GEMINI_API_KEY", "")
    from config.settings import DAILY_CAP, SCORE_THRESHOLD
    discovery.main(day, DB_PATH, FACTORY_DATA, max_vods)
    prontos = ingest.ingest_day(day, DB_PATH, FACTORY_DATA)
    if not prontos:
        log("fonte B: nenhuma VOD pronta.")
        return []
    cands = signals.signals_day(day, FACTORY_DATA)
    log(f"fonte B: {len(cands)} candidatos (gate de voz + janela adaptativa).")
    if not cands:
        return []
    transc = transcribe.transcribe_day(day, FACTORY_DATA, model, api_key) if api_key else {}
    log(f"fonte B: {len(transc)} transcritos.")
    sel = score.score_day(day, FACTORY_DATA, score_model, api_key,
                          float(SCORE_THRESHOLD), int(DAILY_CAP), transcritos=transc or None)
    log(f"fonte B: {len(sel)} selecionados (rubrica 3 eixos).")
    if not sel:
        return []
    cutter.cutter_day(day, FACTORY_DATA, DB_PATH)
    finais = render.render_day(day, FACTORY_DATA)
    if not finais:
        return []
    pack_redes.build_pack(FACTORY_DATA / day, finais)
    for v in prontos:  # limpa raws pesados
        try:
            Path(v["mp4"]).unlink(missing_ok=True)
        except Exception:
            pass
    return finais


def main(argv: list[str]) -> int:
    day, max_n, fonte = "", 2, "auto"
    if "--date" in argv:
        day = argv[argv.index("--date") + 1]
    if "--max" in argv:
        try:
            max_n = max(1, int(argv[argv.index("--max") + 1]))
        except ValueError:
            pass
    if "--fonte" in argv:
        fonte = argv[argv.index("--fonte") + 1]
    day = day or _dt.date.today().isoformat()
    FACTORY_DATA.mkdir(parents=True, exist_ok=True)
    log(f"dia {day} fonte={fonte}")

    finais: list[dict] = []
    usou_b = False
    if fonte in ("auto", "a"):
        finais = fonte_a(day, max_n)
    if not finais and fonte in ("auto", "b"):
        if fonte == "auto":
            log("fonte A secou — caindo pra fonte B.")
        usou_b = True
        finais = fonte_b(day)
    if not finais:
        log("nada novo em nenhuma fonte — fim.")
        return 0
    log(f"finais: {len(finais)} (fonte {'B' if usou_b else 'A'}).")
    return _finalizar(day, finais)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
