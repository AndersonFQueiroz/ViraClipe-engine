"""Marca d'água anti-kiba: handle alternado, alpha, escape ffmpeg."""

from factory import render as R


def test_overlay_so_marca_sem_texto_queimado():
    vf = R.build_overlay_vf("/f.ttf", "Jogada insana", "@alanzoka — url", "@viraclipe.oficial")
    assert vf.count("drawtext") == 2  # só marca topo + marca base
    assert "@viraclipe.oficial" in vf
    assert "Jogada insana" not in vf and "@alanzoka" not in vf
    assert "white@0.55" in vf  # semi-transparente
    assert "lt(mod(t,12),6)" in vf and "gte(mod(t,12),6)" in vf  # alterna 6s/6s


def test_escape_ffmpeg():
    assert R._ff_esc("12:30 jogo") == "12\\:30 jogo"
    assert "'" not in R._ff_esc("d'água")


def test_handle_default():
    vf = R.build_overlay_vf("/f.ttf", "T", "C")
    assert "@viraclipe.oficial" in vf
