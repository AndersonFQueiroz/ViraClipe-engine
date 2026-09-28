"""Dia da fonte A (clips): descobre → processa → QC → prévias p/ aprovar.

Nada é agendado aqui: o dono toca ✅/❌ no Telegram e o bot agenda.
Uso: python3 tools/clips_day.py [--date AAAA-MM-DD] [--max 2]
Exit: 0 prévias enviadas (ou nada novo), 1 QC falhou.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_PATH, FACTORY_DATA
from factory import aprova, clips, qc


def main(argv: list[str]) -> int:
    day = None
    max_n = 2
    if "--date" in argv:
        day = argv[argv.index("--date") + 1]
    if "--max" in argv:
        try:
            max_n = max(1, int(argv[argv.index("--max") + 1]))
        except ValueError:
            pass
    if not day:
        import datetime as _dt
        day = _dt.date.today().isoformat()
    FACTORY_DATA.mkdir(parents=True, exist_ok=True)
    finais = clips.process_clips_day(day, DB_PATH, FACTORY_DATA, max_n=max_n)
    if not finais:
        print("clips_day: nada novo — fim.")
        return 0
    if qc.main(day, FACTORY_DATA, DB_PATH) != 0:
        print("clips_day: QC FALHOU — nada enviado.")
        return 1
    aprova.marcar_qc_ok(DB_PATH, [str(f.get("cut_id")) for f in finais])
    res = aprova.enviar_previews(day, FACTORY_DATA, DB_PATH)
    print(f"clips_day: prévias {res} — aguardando ✅/❌ no Telegram.")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
