"""Feedback loop: views -> pesos aprendidos.

Uso:
  python3 tools/feedback.py coletar --channel UCxxx   # busca views e casa cortes
  python3 tools/feedback.py aprender                  # correlação -> pesos
  python3 tools/feedback.py status                    # amostras + pesos atuais
Exit 0 ok.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_PATH
from config import secret_loader as _sl
from factory import feedback as F


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "coletar":
        ch = argv[argv.index("--channel") + 1] if "--channel" in argv else ""
        ms = F.coletar(ch, DB_PATH)
        print(f"feedback: {len(ms)} corte(s) casado(s) com views.")
        for m in ms[:10]:
            print(f"  {m['cut_id'][:40]} -> {m['views']} views")
        return 0
    if cmd == "aprender":
        res = F.learn(DB_PATH)
        if not res.get("ok"):
            print(f"feedback: amostra curta ({res.get('amostras')}/{res.get('min')}) — mantendo defaults.")
            return 0
        p = F.apply_learned(Path("data/factory"), res["pesos"], DB_PATH, res["amostras"])
        print(f"feedback: {res['amostras']} amostras {res['correlacoes']} -> {p}")
        return 0
    con_b = __import__("sqlite3").connect(str(DB_PATH)) if DB_PATH.exists() else None
    n = 0
    if con_b is not None:
        try:
            n = con_b.execute("SELECT COUNT(*) FROM feedback_views").fetchone()[0]
        except Exception:
            n = 0
        con_b.close()
    print(f"feedback: amostras={n} pesos_atuais="
          f"score={_sl.score_weights()} signal={_sl.signal_weights()}")
    try:
        print("arquivo:", json.loads(Path("data/pesos_aprendidos.json").read_text(encoding="utf-8")))
    except Exception:
        print("arquivo: ausente (defaults)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
