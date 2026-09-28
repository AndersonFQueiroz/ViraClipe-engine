"""Gate humano: pendentes/aprovar/rejeitar sem rede (Buffer mockado)."""

import json

from factory import aprova as A
from factory import db as _db


def _setup(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    day_dir = tmp_path / "f" / "2026-09-28"
    day_dir.mkdir(parents=True)
    finais = [
        {"cut_id": "clip-A", "streamer": "s", "titulo": "T", "chat": 90,
         "mp4": str(day_dir / "final-clip-A.mp4")},
        {"cut_id": "clip-B", "streamer": "s", "titulo": "T2", "chat": 80,
         "mp4": str(day_dir / "final-clip-B.mp4")},
    ]
    (day_dir / "finais.json").write_text(json.dumps(finais), encoding="utf-8")
    (day_dir / "pack.json").write_text(json.dumps({
        "videos": {"c1": "v1", "c2": "v2"},
        "creditos": {"c1": {"cut_id": "clip-A"}, "c2": {"cut_id": "clip-B"}},
    }), encoding="utf-8")
    con = _db.connect(dbp)
    con.execute("INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao, score_final, titulo, status)"
                " VALUES('clip-A','clip:x','s',0,30,90,'T','qc_ok')")
    con.execute("INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao, score_final, titulo, status)"
                " VALUES('clip-B','clip:y','s',0,30,80,'T2','cut')")
    con.commit()
    con.close()
    return dbp, tmp_path / "f"


def test_pendentes_e_key(tmp_path):
    dbp, fac = _setup(tmp_path)
    p = A.pendentes("2026-09-28", fac, dbp)
    assert {x["cut_id"] for x in p} == {"clip-A", "clip-B"}
    assert A.key_of_cut(fac / "2026-09-28", "clip-B") == "c2"
    assert A.key_of_cut(fac / "2026-09-28", "clip-Z") is None


def test_aprovar_agenda_so_aprovado(tmp_path):
    dbp, fac = _setup(tmp_path)
    chamadas = []
    fake_buf = lambda day, fd, only=None, **k: chamadas.append(list(only or [])) or 0
    res = A.aprovar("2026-09-28", fac, dbp, "clip-A", buffer_main=fake_buf)
    assert res == {"ok": True, "cut_id": "clip-A", "key": "c1"}
    assert chamadas == [["c1"]]  # SÓ o aprovado vai ao Buffer
    con = _db.connect(dbp)
    st = con.execute("SELECT status FROM cortes WHERE cut_id='clip-A'").fetchone()["status"]
    con.close()
    assert st == "agendado"
    # B continua pendente
    assert [x["cut_id"] for x in A.pendentes("2026-09-28", fac, dbp)] == ["clip-B"]


def test_aprovar_recusa_repetido_e_falha_buffer(tmp_path):
    dbp, fac = _setup(tmp_path)
    A.rejeitar(dbp, "clip-B", "ruim")
    res = A.aprovar("2026-09-28", fac, dbp, "clip-B",
                    buffer_main=lambda *a, **k: 0)
    assert not res["ok"] and "pendente" in res["error"]
    res2 = A.aprovar("2026-09-28", fac, dbp, "clip-A",
                     buffer_main=lambda *a, **k: 1)
    assert not res2["ok"] and "exit 1" in res2["error"]
    # sem agendar, continua pendente
    assert [x["cut_id"] for x in A.pendentes("2026-09-28", fac, dbp)] == ["clip-A"]


def test_fila_rollover_dia_seguinte(tmp_path):
    dbp, fac = _setup(tmp_path)
    # lota hoje com 5
    for i in range(5):
        cid = f"x-{i}"
        A._db.init_db(dbp)
        con = A._db.connect(dbp)
        con.execute("INSERT INTO fila(cut_id, dia_alvo, slot, status) VALUES(?,?,?,?)",
                    (cid, "2026-09-28", i, "na_fila"))
        con.commit()
        con.close()
    dia, slot = A.proximo_slot(dbp, "2026-09-28")
    assert dia == "2026-09-29" and slot == 0
    assert A.comprometidos(dbp, "2026-09-28") == 5
    assert A.comprometidos(dbp, "2026-09-29") == 0


def test_enfileirar_e_promover(tmp_path, monkeypatch):
    monkeypatch.setenv("BUFFER_API_KEY", "tok")
    dbp, fac = _setup(tmp_path)
    day_dir = fac / "2026-09-28"
    (day_dir / "clips.json").write_text("[]", encoding="utf-8")
    (day_dir / "final-clip-A.mp4").write_bytes(b"x" * 200_000)
    import datetime as _dt
    res = A.enfileirar("2026-09-28", fac, dbp, "clip-A")
    assert res["ok"] and res["dia_alvo"] == _dt.date.today().isoformat() and res["slot"] == 0
    up = lambda p: "https://cdn/x.mp4"
    ch = lambda t: {"instagram": "i", "tiktok": "t", "youtube": "y"}
    feitas = []
    cr = lambda *a, **k: feitas.append(a[1]) or "p1"
    out = A.promover_fila(fac, dbp, "2026-09-28", channels_fn=ch, create_fn=cr, uploader=up)
    assert out == {"ok": True, "agendados": 1, "falhas": []}
    assert feitas == ["instagram", "tiktok", "youtube"]
    con = A._db.connect(dbp)
    st = con.execute("SELECT status FROM fila WHERE cut_id='clip-A'").fetchone()["status"]
    con.close()
    assert st == "agendado"


def test_definir_titulo_usa_base_ia(tmp_path):
    dbp, fac = _setup(tmp_path)
    day_dir = fac / "2026-09-28"
    (day_dir / "real.mp4").write_bytes(b"x" * 200_000)
    (day_dir / "finais.json").write_text(
        __import__("json").dumps([{"cut_id": "clip-AbcDef123", "streamer": "s",
                                   "titulo": "velho", "descricao": "d",
                                   "hashtags": [], "mp4": str(day_dir / "real.mp4")}]), encoding="utf-8")
    (day_dir / "scored.json").write_text(
        __import__("json").dumps([{"cut_id": "clip-AbcDef123", "streamer": "s",
                                   "titulo": "velho", "descricao": "d",
                                   "hashtags": []}]), encoding="utf-8")
    (day_dir / "clips.json").write_text(
        __import__("json").dumps([{"clip_id": "AbcDef123XYZtwitch", "streamer": "s",
                                   "titulo_clip": "orig", "views": 100,
                                   "duracao": 30.0, "url": "u"}]), encoding="utf-8")
    (day_dir / "pack.json").write_text(
        __import__("json").dumps({
            "videos": {"c1": "v1"},
            "captions": {}, "captions_tt": {},
            "creditos": {"c1": {"cut_id": "clip-AbcDef123"}}}), encoding="utf-8")
    fake_leg = lambda *a, **k: {"titulo": "MEU TITULO", "descricao": "@s festa",
                                "hashtags": ["a"], "viral_clip": 80, "motivo": "m"}
    import factory.score as _S
    _S_orig = _S.legendar_clip
    _S.legendar_clip = lambda *a, **k: fake_leg()
    try:
        res = A.definir_titulo(fac, dbp, "clip-AbcDef123", "meu titulo brabo")
    finally:
        _S.legendar_clip = _S_orig
    assert res["ok"] and res["titulo"] == "meu titulo brabo"
    assert "@s" in res["descricao"]  # resposta mostra a descrição nova
    pack = __import__("json").loads((day_dir / "pack.json").read_text(encoding="utf-8"))
    assert "meu titulo brabo" in pack["titles"]["c1"]
    assert "@s" in pack["captions"]["c1"]


def test_find_day_e_marcar(tmp_path):
    dbp, fac = _setup(tmp_path)
    assert A.find_day_of_cut(fac, "clip-B") == "2026-09-28"
    assert A.find_day_of_cut(fac, "clip-Z") is None
    A.marcar_qc_ok(dbp, ["clip-B"])
    con = _db.connect(dbp)
    st = con.execute("SELECT status FROM cortes WHERE cut_id='clip-B'").fetchone()["status"]
    con.close()
    assert st == "qc_ok"
