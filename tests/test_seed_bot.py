"""Seed + bot leve (sem rede, sem lib Telegram)."""

import csv
import sqlite3
from pathlib import Path

from bot.main import apply_remover, fila_text, parse_remover_args, status_text
from factory import db as _db
from tools import seed_whitelist as SEED


def test_seed_csv_tem_12_e_insere_pendente(tmp_path, monkeypatch):
    csv_src = Path("data/whitelist_seed.csv")
    assert csv_src.exists()
    rows = list(csv.DictReader(csv_src.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 12
    assert {r["plataforma"] for r in rows} >= {"twitch", "youtube", "kick"}
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(SEED, "DB_PATH", dbp)
    monkeypatch.setattr(SEED, "SEED", csv_src)
    assert SEED.seed(dbp, csv_src) == 0
    con = _db.connect(dbp)
    try:
        n = con.execute("SELECT COUNT(*) c FROM streamers").fetchone()["c"]
        on = con.execute("SELECT COUNT(*) c FROM streamers WHERE cortes_liberados=1").fetchone()["c"]
    finally:
        con.close()
    assert n == 12 and on == 0
    assert SEED.activate("alanzoka", "twitch", dbp) == 0
    con = _db.connect(dbp)
    try:
        assert con.execute("SELECT cortes_liberados FROM streamers WHERE handle='alanzoka'").fetchone()["cortes_liberados"] == 1
    finally:
        con.close()


def test_bot_remover_marca_denylist(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    con = _db.connect(dbp)
    con.execute("INSERT INTO streamers(handle, plataforma, cortes_liberados) VALUES('alguem','twitch',1)")
    con.execute("INSERT INTO vods_processados(video_id, plataforma, streamer, duracao) VALUES('v1','twitch','alguem',100)")
    con.execute("INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao, score_final, titulo, status)"
                " VALUES('v1-10','v1','alguem',10,30,80,'T','qc_ok')")
    con.commit()
    con.close()
    cut, motivo = parse_remover_args("/remover v1-10 pedido do autor")
    assert (cut, motivo) == ("v1-10", "pedido do autor")
    res = apply_remover(dbp, cut, motivo)
    assert res["ok"] and res["streamer"] == "alguem"
    con = sqlite3.connect(str(dbp))
    con.row_factory = sqlite3.Row
    try:
        assert con.execute("SELECT status FROM cortes WHERE cut_id='v1-10'").fetchone()["status"].startswith("removido")
        assert con.execute("SELECT denylist FROM streamers WHERE handle='alguem'").fetchone()["denylist"] == 1
    finally:
        con.close()
    assert "whitelist" in status_text(dbp)
    assert apply_remover(dbp, "inexistente")["ok"] is False


def test_fila_text_conta_arquivos(tmp_path):
    day = tmp_path / "2026-09-22"
    day.mkdir()
    (day / "vods.json").write_text('[{"video_id":"v1"}]', encoding="utf-8")
    txt = fila_text("2026-09-22", tmp_path)
    assert "vods.json: 1" in txt and "buffer.json: --" in txt


def test_cron_script_existe_e_aponta_run_diaria():
    p = Path("factory/cron_diario.sh")
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "factory.run_diaria" in txt
    assert "data/logs/cron-" in txt
    import os
    assert os.access(p, os.X_OK)
