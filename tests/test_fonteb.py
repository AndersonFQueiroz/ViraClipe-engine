"""Fonte B: gate de voz, janela adaptativa, rubrica 3 eixos (sem rede)."""

from factory import score as S
from factory import signals as G


def _cw(chat=100.0, ini=100.0, fim=130.0):
    return [{"t_inicio": ini, "t_fim": fim, "chat": chat}]


def _aw(audio=100.0, ini=100.0, fim=130.0):
    return [{"t_inicio": ini, "t_fim": fim, "audio": audio}]


def test_speech_density():
    assert G.speech_density([], 0, 30) == 1.0
    assert G.speech_density([(0, 30)], 0, 30) == 0.0
    assert G.speech_density([(0, 15)], 0, 30) == 0.5
    assert G.speech_density([(0, 10)], 20, 30) == 1.0


def test_fuse_gate_voz():
    base = G.fuse(_cw(), _aw())[0]["combinado"]
    sem_voz = G.fuse(_cw(), _aw(), speech={3: 0.0})[0]
    com_voz = G.fuse(_cw(), _aw(), speech={3: 100.0})[0]
    assert sem_voz["combinado"] < base * 0.5  # pico mudo despenca
    assert com_voz["combinado"] == base  # fala cheia mantém
    assert sem_voz["voz"] == 0.0 and com_voz["voz"] == 100.0


def test_adaptive_bounds_setup_e_trim():
    # fala contínua 60-130, silêncio 130-200: expande p/ trás, trima fim
    sil = [(130, 200)]
    ini, fim = G.adaptive_bounds(100, 130, sil)
    assert ini < 100 and fim <= 131
    assert fim - ini >= 25  # respeita min_dur
    # tudo silencioso: não inventa, mantém min_dur
    ini2, fim2 = G.adaptive_bounds(100, 130, [(0, 500)])
    assert fim2 - ini2 == 25.0


def test_parse_rubrica():
    import json
    data = S.parse_gemini_json(json.dumps({
        "viral_score": 90, "hook": 95, "payoff": 40, "densidade": 88,
        "motivo": "m", "titulo": "t", "descricao": "d", "hashtags": ["a"]}))
    assert (data["hook"], data["payoff"], data["densidade"]) == (95, 40, 88)
    data2 = S.parse_gemini_json('{"viral_score": 70}')
    assert (data2["hook"], data2["payoff"], data2["densidade"]) == (50, 50, 50)


def test_score_carrega_rubrica():
    fake = lambda texto, c: {"viral_score": 80, "hook": 90, "payoff": 30,
                             "densidade": 85, "motivo": "m", "titulo": "T",
                             "descricao": "d @s", "hashtags": []}
    out = S.score_candidatos(
        [{"video_id": "v", "streamer": "s", "t_inicio": 10.0, "duracao": 30.0,
          "chat": 80, "audio": 80, "combinado": 80}],
        {}, "m", "k", threshold=0, daily_cap=5, gemini_fn=fake)
    assert out[0]["rubrica"] == {"hook": 90, "payoff": 30, "densidade": 85}
