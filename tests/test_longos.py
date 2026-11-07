"""Longos 10+ min: janela, parser, slot, thumb (sem rede/ffmpeg real)."""

import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw

from factory import db as DB
from factory import longos as L


def test_janela_normal_10min():
    w = L.janela(1000, 30, 5000)
    assert w is not None
    start, end, dur = w
    assert (start, end, dur) == (715.0, 1315.0, 600.0)


def test_janela_comeco_do_vod():
    w = L.janela(100, 30, 5000)
    assert w is not None
    start, end, dur = w
    assert start == 0.0 and dur == 600.0
    assert start <= 100 <= end


def test_janela_fim_do_vod():
    w = L.janela(4970, 30, 5000)
    assert w is not None
    start, end, dur = w
    assert end == 5000.0 and dur == 600.0
    assert start <= 4970 <= end


def test_janela_vod_curto_pula():
    assert L.janela(100, 30, 500) is None


def test_janela_anchor_fora_clampa():
    w = L.janela(6000, 30, 5000)
    assert w is not None
    assert w[1] == 5000.0 and w[2] == 600.0


def test_parse_texto_rotulos():
    txt = ("thumb: NÃO É POSSÍVEL\nKKKKKKKK\n"
           "titulo: MOUNT JOGANDO UNTIL DAWN\n"
           "desc: linha 1\nlinha 2")
    p = L.parse_texto(txt)
    assert p["thumb"] == "NÃO É POSSÍVEL\nKKKKKKKK"
    assert p["titulo"] == "MOUNT JOGANDO UNTIL DAWN"
    assert p["desc"] == "linha 1\nlinha 2"


def test_parse_texto_simples_e_vazio():
    assert L.parse_texto("só o texto da thumb") == {"thumb": "só o texto da thumb"}
    p = L.parse_texto("thumb: \ntitulo: X")
    assert p == {"thumb": "", "titulo": "X"}


def test_longo_id_curto_e_estavel():
    a, b = L.longo_id("clip-abc"), L.longo_id("clip-abc")
    assert a == b and len(a) == 11 and a.startswith("l")
    assert a != L.longo_id("clip-outro")


def test_proximo_slot_longo(tmp_path: Path):
    db = tmp_path / "v.db"
    DB.init_db(db)
    agora = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.timezone.utc)
    assert L.proximo_slot_longo(db, agora) == "2026-11-07T13:30:00+00:00"
    con = DB.connect(db)
    con.execute("INSERT INTO longos(longo_id,status,due_at) VALUES(?,?,?)",
                ("l0000000001", "agendado", "2026-11-07T13:30:00+00:00"))
    con.commit()
    con.close()
    assert L.proximo_slot_longo(db, agora) == "2026-11-07T16:30:00+00:00"
    assert L.due_brt("2026-11-07T13:30:00+00:00") == "07/11 10:30 BRT"


def _frame(path: Path, color):
    im = Image.new("RGB", (640, 360), color)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 240, 240], fill=(30, 30, 30))
    im.save(path, "JPEG", quality=90)


def test_thumb_base_e_texto(tmp_path: Path):
    frames = []
    for i, c in enumerate([(120, 40, 40), (40, 120, 40), (40, 40, 120)]):
        p = tmp_path / f"f{i}.jpg"
        _frame(p, c)
        frames.append(p)
    face = tmp_path / "face.jpg"
    im = Image.new("RGB", (1280, 720), (90, 70, 60))
    ImageDraw.Draw(im).ellipse([520, 180, 760, 460], fill=(230, 190, 160))
    im.save(face, "JPEG", quality=90)
    base = tmp_path / "base.jpg"
    assert L.montar_thumb_base(frames, face, (520, 180, 240, 280), base)
    assert base.exists() and base.stat().st_size > 20_000
    out = tmp_path / "final.jpg"
    assert L.render_thumb_texto(base, "NÃO É POSSÍVEL\nKKKKKKKK", out)
    assert out.exists() and out.stat().st_size > 20_000
    with Image.open(out) as fim:
        assert fim.size == (1280, 720)
    sem = tmp_path / "sem.jpg"
    assert L.render_thumb_texto(base, "", sem)
    assert sem.exists()
