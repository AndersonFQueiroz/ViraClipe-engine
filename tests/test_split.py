"""Split público/full: fork roda capado, dono injeta tempero sem commitar."""

import json

from config import secret_loader as SL
from factory import pack_redes as P
from factory import qc as Q
from factory import score as SC
from factory import signals as SG


def test_publico_capado_default(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("VIRACLIP_") or k.startswith("SCORE_W_") or k.startswith("SIGNAL_W_"):
            monkeypatch.delenv(k, raising=False)
    assert SL.is_full_mode() is False
    assert SL.mode_label() == "publico-capado"
    assert "viral_score" in SL.get_gemini_prompt()
    assert SC.score_final(90, 80, None) == 76.0  # 0.5*90+0.2*80+0.3*50
    assert P._live_tags() == P.TAGS_BASE
    assert Q.load_blocklist()  # pública mínima existe


def test_full_via_env(monkeypatch):
    monkeypatch.setenv("VIRACLIP_PROMPT", "PROMPT PRIVADO viral_score custom")
    monkeypatch.setenv("VIRACLIP_BLOCKLIST", "termo-secreto-xyz, outro")
    monkeypatch.setenv("VIRACLIP_TAGS", "cortes viral secreto")
    monkeypatch.setenv("VIRACLIP_CTA_TIKTOK", "Segue o @ViraClipe FULL 👇")
    monkeypatch.setenv("SCORE_W_CHAT", "0.6")
    monkeypatch.setenv("SCORE_W_AUDIO", "0.1")
    monkeypatch.setenv("SCORE_W_LLM", "0.3")
    assert SL.is_full_mode() is True
    assert SL.get_gemini_prompt() == "PROMPT PRIVADO viral_score custom"
    assert "termo-secreto-xyz" in Q.load_blocklist()
    assert "secreto" in P._live_tags()
    assert P._live_cta()["tiktok"] == "Segue o @ViraClipe FULL 👇"
    # 0.6*90+0.1*80+0.3*50 = 77.0
    assert SC.score_final(90, 80, None) == 77.0


def test_full_via_b64_e_pack_json(monkeypatch):
    import base64

    monkeypatch.setenv("VIRACLIP_PROMPT_B64", base64.b64encode("PROMPT B64".encode()).decode())
    pack = {"cta": {"tiktok": "CTA JSON"}, "tags_base": ["json1", "json2"], "handle": "@HandleJSON"}
    monkeypatch.setenv("VIRACLIP_PACK_JSON", json.dumps(pack))
    assert SL.get_gemini_prompt() == "PROMPT B64"
    assert P._live_tags() == ["json1", "json2"]
    assert P._live_cta()["tiktok"] == "CTA JSON"
    assert P._live_handle() == "@HandleJSON"


def test_signal_weights_override(monkeypatch):
    msgs = [{"t": float(i), "emotes": 0} for i in range(60)]
    cw = SG.chat_windows(msgs)
    peaks = [(float(t), -20.0) for t in range(60)]
    aw = SG.audio_windows(peaks)
    monkeypatch.setenv("SIGNAL_W_CHAT", "0.9")
    monkeypatch.setenv("SIGNAL_W_AUDIO", "0.1")
    out = SG.fuse(cw, aw, top_n=2)
    assert out  # só garante que override não quebra o fuse
