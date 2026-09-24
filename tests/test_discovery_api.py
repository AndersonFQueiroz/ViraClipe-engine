"""Discovery real (Twitch/YouTube) com HTTP mockado — sem rede, sem quota."""

from factory import discovery as D


def test_dur_parsers():
    assert D._twitch_dur("2h15m30s") == 2 * 3600 + 15 * 60 + 30
    assert D._twitch_dur("45m10s") == 45 * 60 + 10
    assert D._twitch_dur("x") == 0.0
    assert D._yt_dur("PT1H2M3S") == 3723.0
    assert D._yt_dur("PT28M47S") == 28 * 60 + 47
    assert D._yt_dur("") == 0.0


def test_sem_credencial_retorna_vazio():
    assert D.fetch_twitch_vods("alguem") == []
    assert D.fetch_youtube_vods("alguem") == []


def _twitch_get(url, headers=None, params=None, timeout=30):
    if "users" in url:
        return {"data": [{"id": "123", "login": "alguem"}]}
    return {"data": [{
        "id": "999", "url": "https://www.twitch.tv/videos/999",
        "title": "live insana", "duration": "1h2m3s",
        "view_count": 5000, "published_at": "2026-09-23T20:00:00Z",
    }]}


def _twitch_post(url, data, timeout):
    class R:
        def json(self):
            return {"access_token": "tok", "expires_in": 100}
    return R()


def test_twitch_mock(monkeypatch):
    D._TWITCH_TOKEN = ""
    out = D.fetch_twitch_vods("alguem", "id", "sec", http_get=_twitch_get, http_post=_twitch_post)
    assert len(out) == 1
    v = out[0]
    assert v["video_id"] == "twitch:999"
    assert v["duracao"] == 3723.0
    assert v["viewers"] == 5000
    assert v["streamer"] == "alguem"
    D._TWITCH_TOKEN = ""


def _yt_get(url, headers=None, params=None, timeout=30):
    if "channels" in url and params.get("forHandle"):
        return {"items": [{"id": "UCXYZ"}]}
    if "channels" in url:
        return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUPL"}}}] }
    if "playlistItems" in url:
        return {"items": [{"contentDetails": {"videoId": "abc123"}}]}
    return {"items": [{"id": "abc123",
                       "snippet": {"title": "EP 1", "publishedAt": "2026-09-23T10:00:00Z"},
                       "contentDetails": {"duration": "PT28M47S"},
                       "statistics": {"viewCount": "1000"}}]}


def test_youtube_playlist_sem_search():
    out = D.fetch_youtube_vods("@Canal", api_key="k", http_get=_yt_get)
    assert len(out) == 1
    v = out[0]
    assert v["video_id"] == "youtube:abc123"
    assert v["url"] == "https://www.youtube.com/watch?v=abc123"
    assert v["duracao"] == 28 * 60 + 47
    assert v["viewers"] == 1000
