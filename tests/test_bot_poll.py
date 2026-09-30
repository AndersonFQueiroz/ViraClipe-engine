"""Bot sem daemon: roteamento de updates com HTTP mockado."""

import sys
import types


def _load(monkeypatch, tmp_path):
    from pathlib import Path
    ROOT = str(Path(__file__).resolve().parent.parent)
    monkeypatch.syspath_prepend(ROOT)
    for m in list(sys.modules):
        if m == "tools.bot_poll" or m.startswith("tools.bot_poll."):
            del sys.modules[m]
    import importlib
    pkg = types.ModuleType("tools")
    pkg.__path__ = [f"{ROOT}/tools"]
    sys.modules["tools"] = pkg
    bp = importlib.import_module("tools.bot_poll")
    bp.API = "https://x/botT"
    bp.OWNER = "99"
    from factory import db as _db
    _db.init_db(Path(tmp_path) / "t.db")
    monkeypatch.setattr(bp, "DB_PATH", Path(tmp_path) / "t.db")
    monkeypatch.setattr(bp, "FACTORY_DATA", Path(tmp_path) / "f")
    sent = []
    monkeypatch.setattr(bp, "api", lambda method, **k: sent.append((method, k)) or {"ok": True, "result": []})
    return bp, sent


def test_callback_ap_enfileira(tmp_path, monkeypatch):
    bp, sent = _load(monkeypatch, tmp_path)
    from factory import db as _db
    from pathlib import Path
    dbp, fac = Path(tmp_path) / "t.db", Path(tmp_path) / "f"
    dd = fac / "2026-09-30"
    dd.mkdir(parents=True)
    (dd / "finais.json").write_text('[{"cut_id": "clip-X", "titulo": "T", "mp4": "x"}]')
    (dd / "pack.json").write_text(
        '{"videos": {"c1": "x"}, "captions": {"c1": "cap"}, "captions_tt": {"c1": "ctt"},'
        ' "creditos": {"c1": {"cut_id": "clip-X"}}}')
    con = _db.connect(dbp)
    con.execute("INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao, score_final, titulo, status)"
                " VALUES('clip-X','clip:x','s',0,30,80,'T','qc_ok')")
    con.commit()
    con.close()
    import datetime as _dt
    monkeypatch.setattr(bp._ap, "promover_fila", lambda *a, **k: {"ok": True, "agendados": 0})
    bp.handle_callback({"id": "q1", "data": "ap:clip-X",
                        "from": {"id": 99}, "message": {"chat": {"id": 99}}})
    assert any(m == "sendMessage" and "na fila" in str(k) for m, k in sent)
    con = _db.connect(dbp)
    st = con.execute("SELECT status FROM fila WHERE cut_id='clip-X'").fetchone()["status"]
    con.close()
    assert st == "na_fila"


def test_callback_nao_dono_ignorado(tmp_path, monkeypatch):
    bp, sent = _load(monkeypatch, tmp_path)
    bp.handle_callback({"id": "q2", "data": "ap:clip-X",
                        "from": {"id": 1}, "message": {"chat": {"id": 1}}})
    assert not any(m == "sendMessage" and "na fila" in str(k) for m, k in sent)


def test_reply_titulo_chama_definir(tmp_path, monkeypatch):
    bp, sent = _load(monkeypatch, tmp_path)
    chamadas = []
    monkeypatch.setattr(bp._ap, "definir_titulo",
                        lambda *a, **k: chamadas.append(a) or {"ok": True, "titulo": "T", "descricao": "D"})
    bp.handle_message({"chat": {"id": 99}, "from": {"id": 99}, "text": "meu titulo",
                       "reply_to_message": {"caption": "📌 X\n🆔 `clip-X`"}})
    assert chamadas and chamadas[0][2] == "clip-X"
    assert any(m == "sendMessage" for m, k in sent)


def test_offset_persiste(tmp_path, monkeypatch):
    bp, sent = _load(monkeypatch, tmp_path)
    from pathlib import Path
    assert bp.get_offset() == 0
    bp.set_offset(42)
    assert bp.get_offset() == 42
