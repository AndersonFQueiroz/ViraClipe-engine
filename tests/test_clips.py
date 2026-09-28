"""Fonte A (clips Twitch): fetch Helix mockado + anti-repetição."""

from factory import clips as C
from factory import db as _db


def _get(url, headers=None, params=None, timeout=30):
    if "users" in url:
        return {"data": [{"id": "111", "login": "alguem"}]}
    return {"data": [
        {"id": "ClipA", "url": "https://clips.twitch.tv/ClipA",
         "title": "jogada insana", "duration": 28.5, "view_count": 500,
         "created_at": "2026-09-27T20:00:00Z",
         "video_id": "2881197324", "vod_offset": 4020},
        {"id": "ClipB", "url": "https://clips.twitch.tv/ClipB",
         "title": "mesmo momento outro angulo", "duration": 30.0,
         "view_count": 900, "created_at": "2026-09-27T21:00:00Z",
         "video_id": "2881197324", "vod_offset": 4025},  # ±10s = repetido
        {"id": "ClipC", "url": "https://clips.twitch.tv/ClipC",
         "title": "longo demais", "duration": 95.0, "view_count": 5000,
         "created_at": "2026-09-27T22:00:00Z",
         "video_id": "2881197324", "vod_offset": 9000},
    ]}


def _post(url, data, timeout):
    class R:
        def json(self):
            return {"access_token": "tok", "expires_in": 100}
    return R()


def test_fetch_parse():
    from factory import discovery as D
    D._TWITCH_TOKEN = ""
    out = C.fetch_clips("alguem", "id", "sec", http_get=_get, http_post=_post)
    D._TWITCH_TOKEN = ""
    assert len(out) == 3
    assert out[0]["clip_id"] == "ClipA"
    assert out[0]["vod_offset"] == 4020.0
    assert out[1]["views"] == 900


def test_sem_credencial_vazio():
    assert C.fetch_clips("alguem") == []


def test_dedup_camadas(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    con = _db.connect(dbp)
    try:
        a = {"clip_id": "ClipA", "streamer": "s", "vod_id": "v1",
             "vod_offset": 4020.0, "views": 5, "titulo_clip": "t"}
        assert not C.is_clip_duplicate(con, a)
        C.register_clip(con, a)
        con.commit()
        # camada 1: mesmo clip_id
        assert C.is_clip_duplicate(con, dict(a))
        # camada 2: outro ID, mesmo momento (vod+offset±10s)
        b = dict(a, clip_id="ClipOutro", vod_offset=4025.0)
        assert C.is_clip_duplicate(con, b)
        # momento diferente passa
        c = dict(a, clip_id="ClipNovo", vod_offset=5000.0)
        assert not C.is_clip_duplicate(con, c)
    finally:
        con.close()


def test_discover_automatico(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("TWITCH_CLIENT_ID", "id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "sec")
    from factory import discovery as D
    D._TWITCH_TOKEN = "tok"
    # fetch_fn injeta 2 canais com views diferentes
    def _fake_fetch(h, *a, **k):
        return [{"clip_id": f"{h}-1", "streamer": h,
                 "url": "u", "titulo_clip": "t", "duracao": 30.0,
                 "views": 100 if h == "a" else 800,
                 "created_at": "", "vod_id": f"v-{h}", "vod_offset": 100.0}]
    monkeypatch.setattr(C, "fetch_clips", _fake_fetch)
    monkeypatch.setattr(C._disc, "load_whitelist",
                        lambda db: [{"handle": "a", "plataforma": "twitch"},
                                    {"handle": "b", "plataforma": "twitch"}])
    dbp = tmp_path / "t.db"
    out = C.discover_clips("2026-09-28", dbp, tmp_path, max_clips_dia=1,
                           min_views=10)
    assert len(out) == 1 and out[0]["clip_id"] == "b-1"  # maior views
    # 2ª rodada: escolhido não volta; backlog sobrevive
    out2 = C.discover_clips("2026-09-28", dbp, tmp_path, max_clips_dia=5,
                            min_views=10)
    assert [c["clip_id"] for c in out2] == ["a-1"]
    D._TWITCH_TOKEN = ""
    assert os.path.exists(tmp_path / "2026-09-28" / "clips.json")
