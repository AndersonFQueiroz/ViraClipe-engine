"""Dashboard terminal: vods/cortes/posts do dia + whitelist."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from config.settings import DB_PATH, FACTORY_DATA


def main(argv: list[str]) -> int:
    day = argv[0] if argv and len(argv[0]) == 10 else None
    if not DB_PATH.exists():
        print("sem banco ainda — rode run_diaria primeiro.")
        return 1
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    print(f"whitelist: {con.execute('SELECT COUNT(*) c FROM streamers WHERE cortes_liberados=1 AND denylist=0').fetchone()['c']}")
    print(f"denylist: {con.execute('SELECT COUNT(*) c FROM streamers WHERE denylist=1').fetchone()['c']}")
    print(f"vods: {con.execute('SELECT COUNT(*) c FROM vods_processados').fetchone()['c']}")
    for r in con.execute("SELECT cut_id, streamer, score_final, status FROM cortes ORDER BY score_final DESC LIMIT 10"):
        print(f"  {r['cut_id']} @{r['streamer']} {r['score_final']} [{r['status']}]")
    if day:
        for name in ("vods.json", "scored.json", "pack.json", "buffer.json"):
            p = FACTORY_DATA / day / name
            print(f"{name}: {'ok' if p.exists() else '--'}")
            if p.exists() and name == "buffer.json":
                print("  " + json.loads(p.read_text(encoding="utf-8")).__str__()[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
