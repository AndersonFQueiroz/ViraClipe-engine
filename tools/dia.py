"""Dia completo: fonte A (clips, 100% auto) -> se secar, fonte B (VOD, com gate).

- Fonte A: clip integral (só split+zoom) -> QC -> Buffer direto -> log Telegram.
- Fonte B: detecção -> QC -> prévias com ✅/❌ (nada agenda sem o dono).
Roda no cron LOCAL (bot+banco+arquivos juntos). Actions fica só manual.
Uso: python3 tools/dia.py [--date AAAA-MM-DD] [--max 2] [--fonte auto|a|b]
Exit: 0 ok, 1 QC falhou.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_PATH, FACTORY_DATA
from factory import (aprova, clips, cutter, db as _db, discovery, ingest,
                     pack_redes, pack_telegram, post_buffer, qc, render,
                     score, signals, transcribe)

T0 = time.time()


def log(msg: str) -> None:
    print(f"[+{time.time()-T0:6.1f}s] {msg}", flush=True)


def _finalizar_auto(day: str, finais: list[dict]) -> int:
    """Fonte A: 100% automática — QC -> Buffer direto -> log Telegram. Sem botão."""
    if qc.main(day, FACTORY_DATA, DB_PATH) != 0:
        log("QC FALHOU — nada enviado.")
        return 1
    aprova.marcar_qc_ok(DB_PATH, [str(f.get("cut_id")) for f in finais])
    rc_buf = post_buffer.main(day, FACTORY_DATA)
    log(f"fonte A auto-post buffer exit={rc_buf} (3 = sem chave, pack pronto).")
    if rc_buf == 0:
        log(f"fonte A: {aprova.registrar_posts(day, FACTORY_DATA, DB_PATH)} slot(s) ocupado(s).")
    rc_tg = pack_telegram.main(day, FACTORY_DATA)
    log(f"fonte A log Telegram exit={rc_tg}.")
    return 0 if rc_buf in (0, 3) else rc_buf


def _finalizar_gate(day: str, finais: list[dict]) -> int:
    """Fonte B: QC -> prévias com ✅/❌. Nada agenda sem o dono."""
    if not finais:
        return 0
    if qc.main(day, FACTORY_DATA, DB_PATH) != 0:
        log("QC FALHOU — nada enviado.")
        return 1
    aprova.marcar_qc_ok(DB_PATH, [str(f.get("cut_id")) for f in finais])
    res = aprova.enviar_previews(day, FACTORY_DATA, DB_PATH)
    log(f"prévias {res} — aguardando ✅/❌ no Telegram.")
    return 0 if res.get("ok") else 1


def _slots_livres(day: str) -> list[int]:
    """Slots livres E futuros (+15min). Slot passado nunca agenda (Buffer rejeita)."""
    import datetime as _dt

    from factory.aprova import due_at

    _db.init_db(DB_PATH)
    con = _db.connect(DB_PATH)
    try:
        usados = {r["slot"] for r in con.execute(
            "SELECT slot FROM fila WHERE dia_alvo=? AND status IN ('na_fila','agendado')",
            (day,)).fetchall()}
    finally:
        con.close()
    agora = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=15)
    livres = []
    for s in range(5):
        if s in usados:
            continue
        try:
            if _dt.datetime.fromisoformat(due_at(day, s)) <= agora:
                continue
        except ValueError:
            continue
        livres.append(s)
    return livres


def fonte_a(day: str, max_n: int) -> list[dict]:
    log("fonte A: clips da comunidade...")
    livres = _slots_livres(day)[:max(0, max_n)]
    if not livres:
        log("fonte A: sem slot livre hoje.")
        return []
    keys = [f"c{s + 1}" for s in livres]
    log(f"fonte A: slots livres {livres} -> keys {keys}.")
    return clips.process_clips_day(day, DB_PATH, FACTORY_DATA,
                                   max_n=len(livres), keys=keys)


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
    day, max_n, fonte = "", 5, "auto"
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

    # 1º: promove fila aprovada vencida (ontem/aprovado-tarde entra hoje).
    try:
        promo = aprova.promover_fila(FACTORY_DATA, DB_PATH, day)
        if promo.get("agendados"):
            log(f"fila promovida: {promo}")
    except Exception as exc:
        log(f"fila: {type(exc).__name__} (sem chave? segue o dia).")
    livres = max(0, 5 - aprova.comprometidos(DB_PATH, day))
    log(f"slots livres hoje: {livres}/5.")

    finais: list[dict] = []
    usou_b = False
    if fonte in ("auto", "a") and livres > 0:
        finais = fonte_a(day, min(max_n, livres))
    if finais and fonte == "auto":
        # Fonte A é 100% automática: posta direto, sem botão.
        log(f"fonte A: {len(finais)} final(is) — auto-postando.")
        return _finalizar_auto(day, finais)
    if not finais and fonte in ("auto", "b"):
        if fonte == "auto":
            log("fonte A secou — caindo pra fonte B (com aprovação).")
        usou_b = True
        finais = fonte_b(day)
    if not finais:
        log("nada novo em nenhuma fonte — fim.")
        return 0
    log(f"finais: {len(finais)} (fonte {'B' if usou_b else 'A'}).")
    if not usou_b and fonte == "a":
        return _finalizar_auto(day, finais)
    return _finalizar_gate(day, finais)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
