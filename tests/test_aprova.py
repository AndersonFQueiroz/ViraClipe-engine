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


def test_find_day_e_marcar(tmp_path):
    dbp, fac = _setup(tmp_path)
    assert A.find_day_of_cut(fac, "clip-B") == "2026-09-28"
    assert A.find_day_of_cut(fac, "clip-Z") is None
    A.marcar_qc_ok(dbp, ["clip-B"])
    con = _db.connect(dbp)
    st = con.execute("SELECT status FROM cortes WHERE cut_id='clip-B'").fetchone()["status"]
    con.close()
    assert st == "qc_ok"
