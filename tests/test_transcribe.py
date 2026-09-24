"""Transcrição com runner/transcriber mockados — sem ffmpeg nem Gemini."""

import json

from factory import transcribe as T


def _runner_ok(cmd, capture_output=True, text=True, timeout=300):
    class R:
        returncode = 0
    # simula mp3 gerado
    out = cmd[-1]
    with open(out, "wb") as f:
        f.write(b"x" * 5000)
    return R()


def test_extract_cmd_mp3_leve(tmp_path):
    mp3 = tmp_path / "s.mp3"
    assert T.extract_snippet_audio(tmp_path / "in.mp4", 10.0, 30.0, mp3, runner=_runner_ok)
    assert mp3.exists()


def test_transcribe_day_com_cache_e_mock(tmp_path):
    day_dir = tmp_path / "f" / "2026-09-24"
    (day_dir / "audio").mkdir(parents=True)
    mp4 = day_dir / "v.mp4"
    mp4.write_bytes(b"x" * 200_000)
    cands = [{"video_id": "v1", "t_inicio": 10.0, "t_fim": 40.0, "duracao": 30.0,
              "chat": 80.0, "audio": 70.0, "streamer": "alguem"}]
    (day_dir / "candidatos.json").write_text(json.dumps(cands), encoding="utf-8")
    (day_dir / "ingest.json").write_text(json.dumps(
        [{"video_id": "v1", "mp4": str(mp4)}]), encoding="utf-8")
    out = T.transcribe_day("2026-09-24", tmp_path / "f", "m", "k",
                           runner=_runner_ok,
                           transcriber=lambda p: "gameplay insano demais")
    assert out == {"v1:10.0": "gameplay insano demais"}
    assert (day_dir / "transcritos.json").exists()
    # 2ª chamada usa cache (transcriber quebrado não é chamado)
    out2 = T.transcribe_day("2026-09-24", tmp_path / "f", "m", "k",
                            runner=_runner_ok,
                            transcriber=lambda p: 1 / 0)
    assert out2 == out


def test_sem_chave_retorna_vazio(tmp_path):
    assert T.transcribe_day("2026-09-24", tmp_path, "m", "") == {}
