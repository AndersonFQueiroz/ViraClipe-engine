"""Foco de jogo (dono 18/11): 1 mês só de GTA 6.

Cobre: prazo que expira sozinho, match por nome/game_id, rótulo curto na
legenda/título/hashtag, filtro na fonte A (clips) e na fonte B (VODs).
"""
from __future__ import annotations

import json
import os


def _foco(monkeypatch, ate: str = ""):
    for k in list(os.environ):
        if k.startswith("VIRACLIP_GAME"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VIRACLIP_GAMES", "Grand Theft Auto VI")
    monkeypatch.setenv("VIRACLIP_GAME_IDS", "1867279146")
    monkeypatch.setenv("VIRACLIP_GAME_LABELS", "Grand Theft Auto VI=GTA 6")
    if ate:
        monkeypatch.setenv("VIRACLIP_GAMES_UNTIL", ate)


def test_sem_config_nao_filtra(monkeypatch):
    for k in list(os.environ):
        if k.startswith("VIRACLIP_GAME"):
            monkeypatch.delenv(k, raising=False)
    from config import settings as S

    assert not S.focus_active("2026-11-18")
    assert S.focus_match("Valorant")


def test_focus_expira_sozinho(monkeypatch):
    _foco(monkeypatch, ate="2026-12-18")
    from config import settings as S

    assert S.focus_active("2026-11-18")
    assert S.focus_active("2026-12-18")  # inclusivo
    assert not S.focus_active("2026-12-19")
    # expirou: volta a aceitar qualquer jogo
    assert S.focus_match("Valorant", "", "2026-12-19")


def test_match_por_nome_e_game_id(monkeypatch):
    _foco(monkeypatch)
    from config import settings as S

    assert S.focus_match("Grand Theft Auto VI")
    assert S.focus_match("grand theft auto vi")
    assert S.focus_match("", "1867279146")
    assert not S.focus_match("Grand Theft Auto V", "32982")
    assert not S.focus_match("Valorant")
    assert S.focus_jogo("", "1867279146") == "Grand Theft Auto VI"


def test_label_e_hashtag(monkeypatch):
    _foco(monkeypatch)
    from config import settings as S

    assert S.game_label("Grand Theft Auto VI") == "GTA 6"
    assert S.game_hashtag("Grand Theft Auto VI") == "gta6"
    assert S.game_label("Valorant") == "Valorant"
    assert S.game_hashtag("Valorant") == "valorant"


def test_titulo_vod_aliases(monkeypatch):
    _foco(monkeypatch)
    from config import settings as S

    assert S.focus_title_match("GTA 6 é insano")
    assert S.focus_title_match("Grand Theft Auto VI - live completa")
    assert not S.focus_title_match("GTA V nostalgia")
    assert not S.focus_title_match("Podcast do Flow")


def test_discover_clips_so_do_jogo(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "sec")
    _foco(monkeypatch)
    from factory import clips as C

    def _fake(h, *a, **k):
        return [
            {"clip_id": f"{h}-g6", "streamer": h, "url": "u", "titulo_clip": "a",
             "duracao": 30.0, "views": 500, "vod_id": f"v-{h}-1",
             "vod_offset": 10.0, "game_id": "1867279146",
             "jogo": "Grand Theft Auto VI"},
            {"clip_id": f"{h}-v", "streamer": h, "url": "u", "titulo_clip": "b",
             "duracao": 30.0, "views": 999, "vod_id": f"v-{h}-2",
             "vod_offset": 20.0, "game_id": "32982",
             "jogo": "Grand Theft Auto V"},
        ]

    monkeypatch.setattr(C, "fetch_clips", _fake)
    monkeypatch.setattr(C._disc, "load_whitelist",
                        lambda db: [{"handle": "s1", "plataforma": "twitch"},
                                    {"handle": "s2", "plataforma": "twitch"}])
    out = C.discover_clips("2026-11-18", tmp_path / "t.db", tmp_path,
                           max_clips_dia=5, min_views=10, registrar=False)
    assert {c["clip_id"] for c in out} == {"s1-g6", "s2-g6"}


def test_dedupe_mesmo_momento_entre_fontes(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "sec")
    _foco(monkeypatch)
    from factory import clips as C

    def _fake(h, *a, **k):
        return [{"clip_id": f"{h}-1", "streamer": h, "url": "u",
                 "titulo_clip": "a", "duracao": 30.0, "views": 500,
                 "vod_id": "vod-X", "vod_offset": 4020.0,
                 "game_id": "1867279146", "jogo": "Grand Theft Auto VI"}]

    monkeypatch.setattr(C, "fetch_clips", _fake)
    monkeypatch.setattr(C._disc, "load_whitelist",
                        lambda db: [{"handle": "s1", "plataforma": "twitch"},
                                    {"handle": "s2", "plataforma": "twitch"}])
    out = C.discover_clips("2026-11-18", tmp_path / "t.db", tmp_path,
                           max_clips_dia=5, min_views=10, registrar=False)
    assert len(out) == 1  # dois clipadores, mesmo momento -> um só


def test_discovery_filtra_vods_do_jogo(tmp_path, monkeypatch):
    _foco(monkeypatch)
    from factory import db as _db
    from factory import discovery as D

    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    con = _db.connect(dbp)
    con.execute("INSERT INTO streamers(handle,plataforma,cortes_liberados)"
                " VALUES('a','twitch',1)")
    con.execute("INSERT INTO streamers(handle,plataforma,cortes_liberados)"
                " VALUES('yt','youtube',1)")
    con.commit()
    con.close()
    monkeypatch.setattr(D, "_game_names", lambda ids: {
        "1867279146": "Grand Theft Auto VI", "32982": "Grand Theft Auto V"})

    def tw(h):
        return [{"video_id": f"twitch:{p}", "plataforma": "twitch",
                 "streamer": h, "titulo_vod": "x", "game_id": g,
                 "viewers": 10, "duracao": 100}
                for p, g in (("1", "1867279146"), ("2", "32982"))]

    def yt(h):
        return [{"video_id": "youtube:ok", "plataforma": "youtube",
                 "streamer": h, "titulo_vod": "GTA 6 primeira hora",
                 "viewers": 5, "duracao": 100},
                {"video_id": "youtube:no", "plataforma": "youtube",
                 "streamer": h, "titulo_vod": "Podcast do Flow",
                 "viewers": 5, "duracao": 100}]

    out = D.discover("2026-11-18", dbp, tmp_path, max_vods_dia=10,
                     fetchers={"twitch": tw, "youtube": yt})
    assert {v["video_id"] for v in out} == {"twitch:1", "youtube:ok"}
    assert out[0].get("jogo") or out[1].get("jogo") == "Grand Theft Auto VI"


def test_caption_com_rotulo_curto(monkeypatch):
    _foco(monkeypatch)
    from factory import pack_redes as P

    cap, _ = P.caption_for({"streamer": "alanzoka", "titulo": "PRIMEIRO ROUBO",
                            "jogo": "Grand Theft Auto VI"})
    assert "Jogo: GTA 6" in cap


def test_pack_titulo_yt_com_jogo(tmp_path, monkeypatch):
    _foco(monkeypatch)
    from factory import pack_redes as P

    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"0" * 150_000)
    finais = [{"cut_id": "c1", "streamer": "alanzoka",
               "titulo": "PRIMEIRO ROUBO", "jogo": "Grand Theft Auto VI",
               "mp4": str(mp4), "url": "u"}]
    p = P.build_pack(tmp_path, finais)
    pack = json.loads(p.read_text(encoding="utf-8"))
    assert pack["titles"]["c1"] == "@alanzoka — PRIMEIRO ROUBO | GTA 6"


def test_hashtag_curta_do_jogo(tmp_path, monkeypatch):
    _foco(monkeypatch)
    from factory import clips as C

    s = C._clip_to_scored({"clip_id": "x", "streamer": "a", "titulo_clip": "t",
                           "duracao": 30, "views": 100,
                           "jogo": "Grand Theft Auto VI"}, tmp_path / "a.mp4")
    assert s["hashtags"][0] == "gta6"


def test_titulo_ruim_cai_na_ia(tmp_path):
    from factory import clips as C

    s = C._clip_to_scored({"clip_id": "x", "streamer": "a", "titulo_clip": "a",
                           "duracao": 30, "views": 100}, tmp_path / "a.mp4",
                          legenda={"titulo": "MOMENTO INSANO"})
    assert s["titulo"] == "MOMENTO INSANO"
