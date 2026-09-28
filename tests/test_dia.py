"""Orquestrador: A auto-posta, B pede botão (tudo mockado)."""

import sys
import types


def _load_dia(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend("/root/linux/projetos/ViraClipe")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("FACTORY_DATA", str(tmp_path / "f"))
    for m in list(sys.modules):
        if m == "tools.dia" or m.startswith("tools.dia."):
            del sys.modules[m]
    import importlib
    tools_pkg = types.ModuleType("tools")
    tools_pkg.__path__ = ["/root/linux/projetos/ViraClipe/tools"]
    sys.modules["tools"] = tools_pkg
    return importlib.import_module("tools.dia")


def test_fonte_a_autoposta_sem_botao(tmp_path, monkeypatch):
    dia = _load_dia(monkeypatch, tmp_path)
    calls = []
    fin = [{"cut_id": "clip-X", "mp4": "x"}]
    monkeypatch.setattr(dia.clips, "process_clips_day", lambda *a, **k: fin)
    monkeypatch.setattr(dia.qc, "main", lambda *a, **k: 0)
    monkeypatch.setattr(dia.aprova, "marcar_qc_ok", lambda *a, **k: None)
    monkeypatch.setattr(dia.post_buffer, "main",
                        lambda *a, **k: calls.append("buffer") or 0)
    monkeypatch.setattr(dia.pack_telegram, "main",
                        lambda *a, **k: calls.append("tg") or 0)
    monkeypatch.setattr(dia.aprova, "enviar_previews",
                        lambda *a, **k: calls.append("PREVIEW") or {"ok": True})
    assert dia.main(["--fonte", "a"]) == 0
    assert calls == ["buffer", "tg"]  # postou direto, sem botão


def test_fonte_b_pede_botao(tmp_path, monkeypatch):
    dia = _load_dia(monkeypatch, tmp_path)
    calls = []
    fin = [{"cut_id": "v-10", "mp4": "x"}]
    monkeypatch.setattr(dia, "fonte_b", lambda *a, **k: fin)
    monkeypatch.setattr(dia.qc, "main", lambda *a, **k: 0)
    monkeypatch.setattr(dia.aprova, "marcar_qc_ok", lambda *a, **k: None)
    monkeypatch.setattr(dia.post_buffer, "main",
                        lambda *a, **k: calls.append("buffer") or 0)
    monkeypatch.setattr(dia.aprova, "enviar_previews",
                        lambda *a, **k: calls.append("PREVIEW") or {"ok": True, "enviados": 1})
    assert dia.main(["--fonte", "b"]) == 0
    assert calls == ["PREVIEW"]  # nada de Buffer sem o dono
