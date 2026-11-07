"""Reframe split: mediana, clamp e filtro (sem cv2/ffmpeg real)."""

from factory import cutter as C
from factory import reframe as RF


def test_median_box_clamp_par():
    # detecção parcial 80px -> 240 -> mínimo 300, w=300*720/560=385.7->384 (par)
    box = RF.median_box([(100.0, 100.0, 80.0), (110.0, 120.0, 90.0), (105.0, 200.0, 70.0)])
    assert box is not None
    x, y, w, h = box
    assert (w, h) == (384, 300)
    assert x % 2 == 0 and y % 2 == 0
    assert 0 <= x <= 1280 - w and 0 <= y <= 720 - h
    # mediana x=105 -> 105-192 <0 -> clamp 0
    assert x == 0


def test_median_box_rosto_grande_limita():
    # rosto mediano 300px -> 900 -> clamp no máximo 460
    box = RF.median_box([(640.0, 360.0, 300.0)])
    assert box is not None
    x, y, w, h = box
    assert h == 460 and w == 590
    assert x % 2 == 0 and y % 2 == 0


def test_median_box_cabeca_nao_transborda():
    # cabeça real ~1.4x o box Haar: tem que caber com folga no painel 560
    box = RF.median_box([(640.0, 360.0, 150.0)])
    assert box is not None
    x, y, w, h = box
    assert h == 450  # 150*3.0
    assert 210 / h <= 0.6  # cabeça de ~210px ocupa <60% do painel


def test_median_box_vazio():
    assert RF.median_box([]) is None
    assert RF.split_filter(None) is None


def test_split_filter_layout():
    vf = RF.split_filter((360, 80, 308, 240))
    assert vf is not None
    assert "scale=1280:720" in vf
    assert "crop=720:720" in vf
    assert "crop=308:240:360:80" in vf
    assert "vstack" in vf


def test_blur_filter_9x16():
    vf = RF.blur_filter()
    assert "scale=720:1280:force_original_aspect_ratio=increase" in vf
    assert "scale=720:1280:force_original_aspect_ratio=decrease" in vf
    assert f"boxblur={RF.BLUR_SIZE}:2" in vf
    assert "crop=720:1280" in vf
    assert "overlay=(W-w)/2:(H-h)/2" in vf
    assert "setsar=1" in vf
    assert "crop=ih*9/16:ih" not in vf


def test_cut_cmd_blur_por_layout_e_env(monkeypatch):
    from pathlib import Path
    cmd = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4"), layout="blur"))
    assert "force_original_aspect_ratio=increase" in cmd
    assert "boxblur=" in cmd
    assert "crop=ih*9/16:ih" not in cmd
    monkeypatch.setenv("VIRACLIPE_LAYOUT", "blur")
    assert C.layout_ativo() == "blur"
    env_cmd = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4")))
    assert "boxblur=" in env_cmd


def test_cut_cmd_split_e_centro():
    from pathlib import Path
    base = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4"), layout="auto"))
    assert "crop=ih*9/16:ih" in base  # fallback centro
    split = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4"),
                               (360, 80, 308, 240), layout="auto"))
    assert "vstack" in split and "crop=ih*9/16" not in split


def test_layout_default_blur(monkeypatch):
    from pathlib import Path
    monkeypatch.delenv("VIRACLIPE_LAYOUT", raising=False)
    assert C.layout_ativo() == "blur"
    cmd = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4")))
    assert "boxblur=" in cmd and "crop=ih*9/16:ih" not in cmd


def _probe_fake(payload):
    import json
    from types import SimpleNamespace

    def fake(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    return fake


def test_fg_box_16x9():
    from pathlib import Path
    fake = _probe_fake({"streams": [{"width": 1920, "height": 1080}]})
    assert C._fg_box(Path("x.mp4"), runner=fake) == (0, 437, 720, 405)


def test_fg_box_rotacao_90():
    from pathlib import Path
    fake = _probe_fake({"streams": [{"width": 1920, "height": 1080,
                                     "side_data_list": [{"rotation": 90}]}]})
    assert C._fg_box(Path("x.mp4"), runner=fake) == (0, 0, 720, 1280)


def test_fg_box_probe_falha():
    from pathlib import Path

    def fake(cmd, **kwargs):
        raise OSError("sem ffprobe")

    assert C._fg_box(Path("x.mp4"), runner=fake) is None


def test_find_face_box_sem_cv2(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("sem cv2")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from pathlib import Path
    assert RF.find_face_box(Path("x.mp4"), 0, 30) is None
