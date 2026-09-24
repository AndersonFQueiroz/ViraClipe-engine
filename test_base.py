"""Smoke tests da base ViraClipe (sem credenciais, sem rede)."""

from config import settings as S


def test_slots_iguais_reellfy():
    assert S.SLOTS_UTC == [(12, 0), (15, 0), (18, 0), (21, 0), (0, 0)]
    assert len(S.SLOTS_UTC) == 5


def test_defaults_free_e_auto():
    assert S.SCORE_THRESHOLD == 75
    assert S.DAILY_CAP == 5
    assert S.GEMINI_MODEL == "gemini-3.6-flash"


def test_score_formula_documentada():
    # score_final = 0.5*chat + 0.2*audio + 0.3*llm
    chat, audio, llm = 80.0, 70.0, 90.0
    score = 0.5 * chat + 0.2 * audio + 0.3 * llm
    assert score == 81.0
    assert score >= S.SCORE_THRESHOLD
