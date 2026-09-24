"""Testes discovery/ingest/signals/score/qc sem rede nem ffmpeg real."""

import json

from factory import db as _db
from factory import discovery as D
from factory import ingest as I
from factory import qc as Q
from factory import score as SC
from factory import signals as SG


def test_tem_permissao():
    assert D.tem_permissao("cortes liberados, pode postar marcando @")
    assert D.tem_permissao("PODE CLIPAR à vontade")
    assert not D.tem_permissao("todos os direitos reservados")


def test_filter_new_vods_ordena_e_limita():
    vods = [
        {"video_id": "a", "viewers": 100},
        {"video_id": "b", "viewers": 900},
        {"video_id": "c", "viewers": 500},
    ]
    out = D.filter_new_vods(vods, {"b"}, max_vods_dia=5)
    assert [v["video_id"] for v in out] == ["c", "a"]
    assert len(D.filter_new_vods(vods, set(), max_vods_dia=1)) == 1


def test_discover_sem_credencial_nao_quebra(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    con = _db.connect(dbp)
    con.execute("INSERT INTO streamers(handle, plataforma, cortes_liberados) VALUES(?,?,?)",
                ("alguem", "twitch", 1))
    con.commit()
    con.close()
    out = D.discover("2026-09-22", dbp, tmp_path / "f",
                     fetchers={"twitch": lambda h: [], "youtube": lambda h: [],
                               "kick": lambda h: []})
    assert out == []
    assert (tmp_path / "f" / "2026-09-22" / "vods.json").exists()


def test_ingest_com_downloader_mock(tmp_path):
    day_dir = tmp_path / "f" / "2026-09-22"
    day_dir.mkdir(parents=True)
    (day_dir / "vods.json").write_text(json.dumps([
        {"video_id": "v1", "plataforma": "twitch", "streamer": "alguem",
         "url": "https://x/v1"}]), encoding="utf-8")
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)

    def fake_dl(url, out):
        out.write_bytes(b"x" * 200_000)
        return True

    out = I.ingest_day("2026-09-22", dbp, tmp_path / "f",
                       downloader=fake_dl,
                       chat_downloader=lambda u, p: p.write_text("[]", encoding="utf-8"))
    assert len(out) == 1 and out[0]["mp4"].endswith(".mp4")
    con = _db.connect(dbp)
    try:
        assert _db.is_vod_processed(con, "v1")
    finally:
        con.close()


def test_signals_chat_audio_fuse():
    msgs = [{"t": float(i), "emotes": 1 if i % 10 == 0 else 0} for i in range(0, 200)]
    # pico artificial no fim
    msgs += [{"t": 195.0 + j * 0.2, "emotes": 3} for j in range(40)]
    cw = SG.chat_windows(msgs)
    assert cw and max(w["chat"] for w in cw) == 100.0
    peaks = [(float(t), -30.0 if t < 180 else -8.0) for t in range(0, 200, 5)]
    aw = SG.audio_windows(peaks)
    fused = SG.fuse(cw, aw, top_n=5)
    assert 1 <= len(fused) <= 5
    assert all(25.0 <= c["duracao"] <= 70.0 for c in fused)


def test_parse_ebur128():
    txt = "[Parsed_ebur128_0] t: 12.3 M: -18.5 S: -20.1 I: -22.0 LUFS\nt: 13.3 M: -9.2"
    peaks = SG.parse_ebur128(txt)
    assert peaks[0] == (12.3, -18.5)


def test_ebur_cmd_somente_audio():
    from pathlib import Path
    cmd = SG.ebur_cmd(Path("v.mp4"))
    assert "-vn" in cmd and "ebur128" in " ".join(cmd)


def test_score_final_renorm_sem_chat():
    # sem replay: 0.4*80 + 0.6*90 = 86.0
    assert SC.score_final(None, 80.0, 90.0) == 86.0
    # sem chat e sem viral: 0.4*80 + 0.6*50 = 62.0
    assert SC.score_final(None, 80.0, None) == 62.0


def test_build_candidatos_marca_chat_none(tmp_path):
    from factory import signals as SG2
    import json as _json
    day = tmp_path / "d"
    day.mkdir()
    mp4 = day / "v.mp4"
    mp4.write_bytes(b"x" * 200_000)
    chat = day / "v.chat.json"
    chat.write_text("[]", encoding="utf-8")
    item = {"video_id": "v", "streamer": "s", "plataforma": "twitch",
            "url": "https://x", "mp4": str(mp4), "chat": str(chat)}

    class _R:
        stderr = "".join(f"[x] t: {t}.0 M: -20.0\n" for t in range(0, 120, 5))
        stdout = ""

    out = SG2.build_candidatos(day, item,
                               runner=lambda *a, **k: _R())
    assert out and all(c["chat"] is None for c in out)


def test_llm_retry():
    from factory import net as _net

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("503 UNAVAILABLE temporário")
        return "ok"

    assert _net.llm_call(flaky, wait=0.01) == "ok"
    assert len(calls) == 2

    def fatal():
        raise ValueError("resposta sem JSON")

    try:
        _net.llm_call(fatal, wait=0.01)
        assert False, "devia levantar"
    except ValueError:
        pass


def test_score_final_e_fallback_sem_chave():
    cands = [{"video_id": "v1", "t_inicio": 10.0, "chat": 90.0, "audio": 80.0,
              "streamer": "alguem", "plataforma": "twitch", "url": "https://x"}]
    out = SC.score_candidatos(cands, api_key="", threshold=75.0, daily_cap=5)
    # fallback viral=50 -> 0.5*90+0.2*80+0.3*50 = 76.0
    assert out and out[0]["score_final"] == 76.0
    assert "alguem" in out[0]["titulo"]

    def fake_gemini(texto, c):
        return {"viral_score": 95, "titulo": "T", "descricao": "D @alguem https://x",
                "hashtags": ["clipe"], "motivo": "hype"}
    out2 = SC.score_candidatos(cands, gemini_fn=fake_gemini, threshold=75.0, daily_cap=5)
    assert out2[0]["viral"] == 95
    assert out2[0]["score_final"] == round(0.5 * 90 + 0.2 * 80 + 0.3 * 95, 1)


def test_qc_bloqueia_sem_credito_e_duplicado(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    day_dir = tmp_path / "f" / "2026-09-22"
    day_dir.mkdir(parents=True)
    scored = [{"cut_id": "v1-10", "video_id": "v1", "streamer": "alguem",
               "t_inicio": 10.0, "titulo": "sem credito nenhum",
               "descricao": "nada", "hashtags": []}]
    (day_dir / "scored.json").write_text(json.dumps(scored), encoding="utf-8")
    ok, errors = Q.qc_day("2026-09-22", tmp_path / "f", dbp, blocklist=[])
    assert not ok and any("crédito" in e or "credito" in e.lower() or "sem crédito" in e.lower() or "SEM" in e or "crédito" in e or "VOD" in e for e in errors)

    # dedup: registra corte e roda de novo com crédito ok mas mp4 ausente
    con = _db.connect(dbp)
    con.execute("INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao, score_final, titulo) VALUES(?,?,?,?,?,?,?)",
                ("v1-10", "v1", "alguem", 10.0, 30.0, 80.0, "T"))
    con.commit()
    con.close()
    scored2 = [{"cut_id": "v1-11", "video_id": "v1", "streamer": "alguem",
                "t_inicio": 10.5, "titulo": "@alguem momento",
                "descricao": "ver https://twitch.tv/x", "hashtags": []}]
    (day_dir / "scored.json").write_text(json.dumps(scored2), encoding="utf-8")
    ok2, errors2 = Q.qc_day("2026-09-22", tmp_path / "f", dbp, blocklist=[])
    assert not ok2 and any("duplicado" in e for e in errors2)
