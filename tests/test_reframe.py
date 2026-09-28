"""Reframe split: mediana, clamp e filtro (sem cv2/ffmpeg real)."""

from factory import cutter as C
from factory import reframe as RF


def test_median_box_clamp_par():
    # rosto mediano 80px -> h=200 (mínimo), w=200*720/560=257.1->256 (par)
    box = RF.median_box([(100.0, 100.0, 80.0), (110.0, 120.0, 90.0), (105.0, 200.0, 70.0)])
    assert box is not None
    x, y, w, h = box
    assert (w, h) == (256, 200)
    assert x % 2 == 0 and y % 2 == 0
    assert 0 <= x <= 1280 - w and 0 <= y <= 720 - h
    # mediana x=105 -> 105-154 <0 -> clamp 0
    assert x == 0


def test_median_box_rosto_grande_limita():
    # rosto mediano 300px -> 600 -> clamp no máximo 360
    box = RF.median_box([(640.0, 360.0, 300.0)])
    assert box is not None
    x, y, w, h = box
    assert h == 360 and w == 462
    assert x % 2 == 0 and y % 2 == 0


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


def test_cut_cmd_split_e_centro():
    from pathlib import Path
    base = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4")))
    assert "crop=ih*9/16:ih" in base  # fallback centro
    split = " ".join(C.cut_cmd(Path("i.mp4"), 0, 30, Path("o.mp4"), (360, 80, 308, 240)))
    assert "vstack" in split and "crop=ih*9/16" not in split


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
