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


def test_slot_passado_e_pulado(tmp_path):
    dbp = tmp_path / "t.db"
    A._db.init_db(dbp)
    # 22h UTC: só resta o slot 21h BRT (00h UTC+1d)
    dia, slot = A.proximo_slot(dbp, "2026-09-28", "2026-09-28T22:00:00+00:00")
    assert (dia, slot) == ("2026-09-28", 4)
    # 23h59 UTC: amanhã
    dia2, slot2 = A.proximo_slot(dbp, "2026-09-28", "2026-09-28T23:50:00+00:00")
    assert (dia2, slot2) == ("2026-09-29", 0)


def test_enfileirar_e_promover(tmp_path, monkeypatch):
    monkeypatch.setenv("BUFFER_API_KEY", "tok")
    dbp, fac = _setup(tmp_path)
    day_dir = fac / "2026-09-28"
    (day_dir / "clips.json").write_text("[]", encoding="utf-8")
    (day_dir / "final-clip-A.mp4").write_bytes(b"x" * 200_000)
    import datetime as _dt
    res = A.enfileirar("2026-09-28", fac, dbp, "clip-A")
    assert res["ok"] and res["dia_alvo"] >= _dt.date.today().isoformat()
    assert 0 <= res["slot"] < 5
    up = lambda p: "https://cdn/x.mp4"
    ch = lambda t: {"instagram": "i", "tiktok": "t", "youtube": "y"}
    feitas = []
    cr = lambda *a, **k: feitas.append(a[1]) or "p1"
    out = A.promover_fila(fac, dbp, _dt.date.today().isoformat(),
                          channels_fn=ch, create_fn=cr, uploader=up)
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
    assert pack["captions"]["c1"] == "meu titulo brabo"  # só título, sem desc


def test_definir_titulo_vod_regen_descricao(tmp_path, monkeypatch):
    import factory.score as _S
    monkeypatch.setattr(_S, "legendar_clip",
                        lambda *a, **k: {"titulo": "T", "descricao": "@s susto",
                                         "hashtags": ["h"], "viral_clip": 70,
                                         "motivo": "m"})
    dbp, fac = _setup(tmp_path)
    day_dir = fac / "2026-09-28"
    (day_dir / "real.mp4").write_bytes(b"x" * 200_000)
    for name in ("scored.json", "finais.json"):
        (day_dir / name).write_text(
            __import__("json").dumps([{"cut_id": "twitch:9-100", "streamer": "s",
                                       "titulo": "velho", "descricao": "d",
                                       "duracao": 30, "hashtags": [],
                                       "mp4": str(day_dir / "real.mp4")}]), encoding="utf-8")
    (day_dir / "pack.json").write_text(
        __import__("json").dumps({
            "videos": {"c1": "v1"}, "captions": {}, "captions_tt": {},
            "creditos": {"c1": {"cut_id": "twitch:9-100"}}}), encoding="utf-8")
    res = A.definir_titulo(fac, dbp, "twitch:9-100", "susto brabo")
    assert res["ok"] and res["descricao"] == "@s susto"


def test_definir_descricao_e_fila_sync(tmp_path):
    dbp, fac = _setup(tmp_path)
    day_dir = fac / "2026-09-28"
    (day_dir / "real.mp4").write_bytes(b"x" * 200_000)
    for name in ("scored.json", "finais.json"):
        (day_dir / name).write_text(
            __import__("json").dumps([{"cut_id": "clip-A", "streamer": "s",
                                       "titulo": "T", "descricao": "velha",
                                       "hashtags": [], "mp4": str(day_dir / "real.mp4")}]), encoding="utf-8")
    res = A.definir_descricao(fac, dbp, "clip-A", "d: minha desc")
    assert res["ok"] and res["descricao"] == "minha desc"
    pack = __import__("json").loads((day_dir / "pack.json").read_text(encoding="utf-8"))
    assert pack["captions"]["c1"] == "T"  # só título mesmo com d: nova
    # vazia recusa
    assert not A.definir_descricao(fac, dbp, "clip-A", "  ")["ok"]


def test_listar_fila(tmp_path):
    dbp, fac = _setup(tmp_path)
    import datetime as _dt
    hoje = _dt.date.today().isoformat()
    con = A._db.connect(dbp)
    con.execute("INSERT INTO fila(cut_id, titulo, dia_alvo, slot, status) VALUES(?,?,?,?,?)",
                ("clip-A", "T", hoje, 0, "na_fila"))
    con.execute("INSERT INTO fila(cut_id, titulo, dia_alvo, slot, status) VALUES(?,?,?,?,?)",
                ("clip-B", "T2", "2000-01-01", 0, "agendado"))
    con.commit()
    con.close()
    rows = A.listar_fila(dbp)
    assert [r["cut_id"] for r in rows] == ["clip-A"]


def test_definir_jogo_vod(tmp_path):
    dbp, fac = _setup(tmp_path)
    day_dir = fac / "2026-09-28"
    (day_dir / "real.mp4").write_bytes(b"x" * 200_000)
    for name in ("scored.json", "finais.json"):
        (day_dir / name).write_text(
            __import__("json").dumps([{"cut_id": "twitch:9-100", "streamer": "s",
                                       "titulo": "T", "descricao": "d",
                                       "duracao": 30, "hashtags": [],
                                       "mp4": str(day_dir / "real.mp4")}]), encoding="utf-8")
    (day_dir / "pack.json").write_text(
        __import__("json").dumps({
            "videos": {"c1": "v1"}, "captions": {}, "captions_tt": {},
            "creditos": {"c1": {"cut_id": "twitch:9-100"}}}), encoding="utf-8")
    res = A.definir_jogo(fac, dbp, "twitch:9-100", "Jogo Lindo")
    assert res["ok"] and res["jogo"] == "Jogo Lindo"
    pack = __import__("json").loads((day_dir / "pack.json").read_text(encoding="utf-8"))
    assert pack["captions"]["c1"] == "T"  # só título, sem linha de jogo
    assert not A.definir_jogo(fac, dbp, "twitch:9-100", "  ")["ok"]


def test_tabela_primeiro_sem_arquivos(tmp_path):
    """Nuvem sem day-files: definir/enfileirar via tabela previews."""
    from factory import db as _db
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    fac = tmp_path / "f"  # SEM dirs de dia
    con = _db.connect(dbp)
    con.execute("INSERT INTO previews(cut_id, dia, streamer, titulo, descricao, caption,"
                " caption_tt, url, jogo) VALUES(?,?,?,?,?,?,?,?,?)",
                ("clip-Z", "2026-10-02", "s", "T velho", "d velha", "cap", "ctt",
                 "https://clips.twitch.tv/Z", ""))
    con.execute("INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao,"
                " score_final, titulo, status) VALUES('clip-Z','clip:z','s',0,30,80,'T velho','qc_ok')")
    con.commit()
    con.close()
    assert A.find_day(dbp, fac, "clip-Z") == "2026-10-02"
    from factory import pack_redes as _P
    assert _P.caption_for({"video_id": "clip:z", "streamer": "s",
                            "titulo": "T", "descricao": "d",
                            "hashtags": [], "jogo": "Jogo Novo"})[0] == "T"
    res = A.definir_jogo(fac, dbp, "clip-Z", "Jogo Novo")
    assert res["ok"] and res["jogo"] == "Jogo Novo"
    res2 = A.definir_titulo(fac, dbp, "clip-Z", "Titulo Novo",
                            gemini_fn=lambda *a, **k: {"titulo": "Titulo Novo",
                                                       "descricao": "@s massa",
                                                       "hashtags": ["a"], "viral_score": 80})
    assert res2["ok"] and res2["titulo"] == "Titulo Novo"
    assert A.prev_row(dbp, "clip-Z")["titulo"] == "Titulo Novo"
    res3 = A.enfileirar("2026-10-02", fac, dbp, "clip-Z")
    assert res3["ok"]  # snapshot veio da tabela, sem arquivos


def test_parse_resposta_tudo_de_uma_vez():
    p = A.parse_resposta("E morreu\nd: @alanzoka caiu kkkk\njogo: GTA V")
    assert p == {"titulo": "E morreu", "descricao": "@alanzoka caiu kkkk",
                 "jogo": "GTA V"}


def test_parse_resposta_inline_uma_linha():
    p = A.parse_resposta("E morreu d: @alanzoka caiu kkkk jogo: GTA V")
    assert p == {"titulo": "E morreu", "descricao": "@alanzoka caiu kkkk",
                 "jogo": "GTA V"}


def test_parse_resposta_parciais():
    assert A.parse_resposta("jogo: GTA V") == {"jogo": "GTA V"}
    assert A.parse_resposta("D: maiúsculo ok") == {"descricao": "maiúsculo ok"}
    assert A.parse_resposta("só título") == {"titulo": "só título"}
    assert A.parse_resposta("  \n ") == {}
    # continuação pertence à seção aberta pelo marcador
    p = A.parse_resposta("jogo: X\nparte um")
    assert p.get("titulo") is None and p["jogo"] == "X parte um"
    p = A.parse_resposta("Título aqui\nd: desc aqui")
    assert p == {"titulo": "Título aqui", "descricao": "desc aqui"}


def test_aplicar_resposta_ordem_titulo_d_jogo(tmp_path, monkeypatch):
    dbp, fac = _setup(tmp_path)
    ordem = []
    monkeypatch.setattr(A, "definir_titulo",
                        lambda *a, **k: ordem.append("titulo") or
                        {"ok": True, "titulo": a[3], "descricao": "IA"})
    monkeypatch.setattr(A, "definir_descricao",
                        lambda *a, **k: ordem.append("descricao") or
                        {"ok": True, "cut_id": "c", "descricao": "MINHA"})
    monkeypatch.setattr(A, "definir_jogo",
                        lambda *a, **k: ordem.append("jogo") or
                        {"ok": True, "cut_id": "c", "jogo": "GTA V"})
    res = A.aplicar_resposta(fac, dbp, "clip-A",
                             "Título Novo\nd: minha desc\njogo: GTA V")
    assert res["ok"] and ordem == ["titulo", "descricao", "jogo"]
    assert res["descricao"] == "MINHA"  # d: ganha da IA
    msg = A.formatar_resposta(res)
    assert "✏️ título: Título Novo" in msg
    assert "📝 descrição: MINHA" in msg
    assert "🎮 jogo: GTA V" in msg and "✅" in msg


def test_formatar_resposta_so_jogo():
    msg = A.formatar_resposta({"ok": True, "cut_id": "c",
                               "aplicado": ["jogo"], "jogo": "GTA V"})
    assert "🎮 jogo: GTA V" in msg and "✏️" not in msg


def test_find_day_e_marcar(tmp_path):
    dbp, fac = _setup(tmp_path)
    assert A.find_day_of_cut(fac, "clip-B") == "2026-09-28"
    assert A.find_day_of_cut(fac, "clip-Z") is None
    A.marcar_qc_ok(dbp, ["clip-B"])
    con = _db.connect(dbp)
    st = con.execute("SELECT status FROM cortes WHERE cut_id='clip-B'").fetchone()["status"]
    con.close()
    assert st == "qc_ok"
