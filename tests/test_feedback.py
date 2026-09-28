"""Feedback loop: match, correlação e override de pesos (sem rede)."""

from factory import db as _db
from factory import feedback as F


def _seed(dbp, n=8):
    _db.init_db(dbp)
    con = _db.connect(dbp)
    for i in range(n):
        # chat prevê views (alto chat = alto views); audio é ruído
        v = 100 + i * 100
        con.execute(
            "INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao,"
            " chat, audio, viral, score_final, titulo, status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (f"c{i}", "v", "s", 0, 30, float(10 + i * 10), 50.0, 50.0,
             80.0, f"Corte numero {i} titulo unico", "agendado"))
        con.execute(
            "INSERT INTO feedback_views(cut_id, rede, video_id, views, likes, coletado_em)"
            " VALUES(?,?,?,?,?,?)", (f"c{i}", "youtube", f"yt{i}", v, 5, "2026-09-28"))
    con.commit()
    con.close()


def test_learn_chat_preve_views(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp)
    res = F.learn(dbp, min_amostras=5)
    assert res["ok"] and res["amostras"] == 8
    assert res["pesos"]["chat"] > res["pesos"]["audio"]  # chat correlaciona, audio não
    assert abs(sum(res["pesos"].values()) - 1.0) < 0.01


def test_learn_amostra_curta(tmp_path):
    dbp = tmp_path / "t.db"
    _seed(dbp, 3)
    res = F.learn(dbp, min_amostras=5)
    assert not res["ok"]


def test_match_por_titulo(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    con = _db.connect(dbp)
    con.execute(
        "INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao,"
        " chat, audio, viral, score_final, titulo, status)"
        " VALUES('clip-X','clip:x','alanzoka',0,30,90,50,80,85,"
        "'o dia que o alanzoka quase tankou','agendado')")
    con.commit()
    con.close()
    ms = F.match_cuts(dbp, [
        {"video_id": "yt1", "titulo": "@alanzoka — o dia que o alanzoka quase tankou",
         "descricao": "x", "views": 500, "likes": 20, "published_at": ""},
        {"video_id": "yt2", "titulo": "outro assunto",
         "descricao": "y", "views": 9999, "likes": 1, "published_at": ""},
    ])
    assert len(ms) == 1 and ms[0]["cut_id"] == "clip-X" and ms[0]["views"] == 500


def test_pesos_env_vence_arquivo(tmp_path, monkeypatch):
    from config import secret_loader as S
    pf = tmp_path / "pesos.json"
    pf.write_text('{"SCORE_W_CHAT": 0.9}', encoding="utf-8")
    monkeypatch.setenv("PESOS_LEARNED_FILE", str(pf))
    monkeypatch.delenv("SCORE_W_CHAT", raising=False)
    assert S.score_weights()[0] == 0.9
    monkeypatch.setenv("SCORE_W_CHAT", "0.1")
    assert S.score_weights()[0] == 0.1  # env explícito vence


def test_migrate_adiciona_colunas(tmp_path):
    import sqlite3
    dbp = tmp_path / "old.db"
    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE cortes(cut_id TEXT PRIMARY KEY, titulo TEXT)")
    con.execute("INSERT INTO cortes VALUES('a','T')")
    con.commit()
    con.close()
    _db.init_db(dbp)  # roda migrate sem quebrar banco antigo
    con = _db.connect(dbp)
    cols = {r[1] for r in con.execute("PRAGMA table_info(cortes)").fetchall()}
    con.close()
    assert {"voz", "rubrica"} <= cols
