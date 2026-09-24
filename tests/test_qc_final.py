"""Regressão: QC valida final-*.mp4 (arquivo postado), não só corte-*.mp4."""

import json

from factory import db as _db
from factory import qc as Q


def _ffprobe_ok(*args, **kwargs):
    class R:
        stdout = json.dumps({
            "format": {"duration": "30.0", "size": "200000"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        })
    return R()


def _scored(cut_id="v1-10"):
    return [{
        "cut_id": cut_id, "video_id": "v1", "streamer": "alguem",
        "t_inicio": 10.0, "titulo": "@alguem momento insano",
        "descricao": "ver https://twitch.tv/videos/1", "hashtags": ["clipe"],
    }]


def test_qc_prefere_final_mp4(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    day_dir = tmp_path / "f" / "2026-09-24"
    day_dir.mkdir(parents=True)
    (day_dir / "scored.json").write_text(json.dumps(_scored()), encoding="utf-8")
    # só o final existe (cenário real pós-render) com faststart válido
    (day_dir / "final-v1-10.mp4").write_bytes(b"x" * 50_000 + b"moov" + b"y" * 60_000 + b"mdat" + b"z" * 100_000)
    ok, errors = Q.qc_day("2026-09-24", tmp_path / "f", dbp, runner=_ffprobe_ok, blocklist=[])
    assert ok, errors


def test_qc_ignora_cut_em_progresso(tmp_path):
    """Cutter insere status='cut' antes do QC — não pode se auto-duplicar."""
    from factory import db as _db2

    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    con = _db.connect(dbp)
    con.execute(
        "INSERT INTO cortes(cut_id, video_id, streamer, t_inicio, duracao, score_final, titulo, status)"
        " VALUES(?,?,?,?,?,?,?,?)",
        ("v9-10", "v9", "alguem", 10.0, 30.0, 80.0, "T", "cut"),
    )
    con.commit()
    assert _db.is_cut_duplicate(con, "v9", 10.0) is False
    con.execute("UPDATE cortes SET status='qc_ok' WHERE cut_id='v9-10'")
    con.commit()
    assert _db.is_cut_duplicate(con, "v9", 10.5) is True
    con.close()


def test_qc_sem_nenhum_mp4_falha(tmp_path):
    dbp = tmp_path / "t.db"
    _db.init_db(dbp)
    day_dir = tmp_path / "f" / "2026-09-24"
    day_dir.mkdir(parents=True)
    (day_dir / "scored.json").write_text(json.dumps(_scored()), encoding="utf-8")
    ok, errors = Q.qc_day("2026-09-24", tmp_path / "f", dbp, runner=_ffprobe_ok, blocklist=[])
    assert not ok and any("mp4 ausente" in e for e in errors)
