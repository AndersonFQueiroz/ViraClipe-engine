"""Auto-recovery YT: erro de mídia -> re-upload fresco + reagenda (mockado)."""

from factory import post_buffer as P


def test_recupera_post_quebrado(tmp_path, monkeypatch):
    from factory import db as _db
    from pathlib import Path
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    mp4 = tmp_path / "final-x.mp4"
    mp4.write_bytes(b"x" * 200_000)
    con = _db.connect(dbp)
    con.execute("INSERT INTO posts(cut_id, rede, buffer_id, agendado_para)"
                " VALUES('c1','youtube','p-old','2026-10-01T15:00:00+00:00')")
    con.execute("INSERT INTO fila(cut_id, mp4, titulo, caption, caption_tt,"
                " dia_alvo, slot, status, criado_em)"
                " VALUES('c1',?,?,?,?,?,?,?,?)",
                (str(mp4), "T", "cap", "ctt", "2026-10-01", 0,
                 "agendado", "2026-10-01"))
    con.commit()
    con.close()
    monkeypatch.setattr(P, "posts_com_erro",
                        lambda tok, horas=48: [{"post_id": "p-old", "due": "x", "error": "media"}])
    monkeypatch.setattr(P, "channels", lambda tok: {"youtube": "y"})
    monkeypatch.setattr(P, "create_post", lambda *a, **k: "p-new")
    monkeypatch.setattr(P, "delete_post", lambda *a, **k: True)
    import factory.upload_public as _U
    monkeypatch.setattr(_U, "upload", lambda p: "https://cdn/novo.mp4")
    res = P.recuperar_youtube(tmp_path, dbp, token="t", hoje="2026-10-01")
    assert res["ok"] and len(res["recuperados"]) == 1 and not res["falhas"]
    con = _db.connect(dbp)
    row = con.execute("SELECT buffer_id FROM posts WHERE cut_id='c1' AND rede='youtube'").fetchone()
    con.close()
    assert row["buffer_id"] == "p-new"


def test_sem_token_ou_sem_erro(tmp_path, monkeypatch):
    from factory import db as _db
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    assert P.recuperar_youtube(tmp_path, dbp, token="")["ok"] is False
    monkeypatch.setattr(P, "posts_com_erro", lambda tok, horas=48: [])
    assert P.recuperar_youtube(tmp_path, dbp, token="t") == {
        "ok": True, "recuperados": [], "falhas": []}
