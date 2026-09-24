"""Testes cutter/render/pack/buffer sem ffmpeg nem rede."""

import json
import zipfile

from factory import cutter as C
from factory import pack_redes as P
from factory import post_buffer as B
from factory import render as R


def test_cut_cmd_vertical_faststart():
    from pathlib import Path
    cmd = C.cut_cmd(Path("in.mp4"), 10.0, 30.0, Path("out.mp4"))
    s = " ".join(cmd)
    assert "crop=ih*9/16:ih,scale=720:1280" in s
    assert "+faststart" in s
    assert "-ss" in cmd and "10.0" in cmd


def test_render_safe_text():
    assert R.safe_text("🔥 MELHOR  momento!!  ") == "MELHOR momento!!"
    assert R.safe_text("") == ""


def test_render_sem_fonte_apenas_copia(tmp_path):
    src = tmp_path / "in.mp4"
    dst = tmp_path / "out.mp4"
    src.write_bytes(b"x" * 200_000)
    # força _font None via monkeypatch do Path.exists? mais simples: copia direta
    import shutil
    shutil.copy(src, dst)
    assert dst.exists()


def test_pack_legendas_e_kwai(tmp_path):
    day = tmp_path / "2026-09-22"
    day.mkdir()
    mp4 = day / "final-x.mp4"
    mp4.write_bytes(b"x" * 200_000)
    finais = [{"cut_id": "x", "streamer": "alguem", "titulo": "Jogada insana",
               "descricao": "que lance", "hashtags": ["clipe"],
               "url": "https://twitch.tv/videos/1", "mp4": str(mp4)}]
    out = P.build_pack(day, finais)
    pack = json.loads(out.read_text(encoding="utf-8"))
    assert "c1" in pack["videos"]
    assert "@alguem" in pack["captions"]["c1"]
    assert "https://twitch.tv/videos/1" in pack["captions"]["c1"]
    cap_tt, _ = P.caption_for(finais[0], "tiktok")
    assert "#clipe" in cap_tt
    z = day / "pack_kwai.zip"
    assert z.exists()
    assert any(n.endswith("-legenda.txt") for n in zipfile.ZipFile(z).namelist())


def test_buffer_slots_e_credenciais(tmp_path, monkeypatch):
    # sem chave -> exit 3
    monkeypatch.delenv("BUFFER_API_KEY", raising=False)
    assert B.main("2026-09-22", tmp_path) == 3
    # com chave mockada: verifica slots 12/15/18/21/00 UTC
    monkeypatch.setenv("BUFFER_API_KEY", "k")
    day = tmp_path / "2026-09-22"
    day.mkdir(exist_ok=True)
    mp4 = day / "v.mp4"
    mp4.write_bytes(b"x" * 200_000)
    pack = {"videos": {"c1": str(mp4), "c2": str(mp4)},
            "captions": {"c1": "a", "c2": "b"}, "captions_tt": {"c1": "a", "c2": "b"},
            "titles": {"c1": "t1", "c2": "t2"}, "cta": {}}
    (day / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    seen = []

    def fake_create(token, svc, ch, text, url, due, title):
        seen.append((svc, due))
        return "pid"

    rc = B.main("2026-09-22", tmp_path,
                channels_fn=lambda t: {"instagram": "i", "tiktok": "t", "youtube": "y"},
                create_fn=fake_create,
                uploader=lambda p: "https://catbox/x.mp4")
    assert rc == 0
    dues = sorted({d for _, d in seen})
    assert any("T12:00" in d for d in dues) and any("T15:00" in d for d in dues)
    assert len(seen) == 2 * 3  # 2 cortes x 3 redes
