"""Gate humano: nada agenda no Buffer sem o dono tocar em ✅.

Fluxo (Termux-first, fonte A é leve):
  tools/clips_day.py → process → QC → marcar_qc_ok → enviar_previews
  dono toca ✅/❌ no Telegram → bot (polling) → aprovar()/rejeitar()
  aprovar() agenda SÓ aquele corte via post_buffer(only=[key]).

Helpers puros (sem lib do Telegram): testáveis sem rede.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from . import net as _net
from . import db as _db

PENDENTE = ("cut", "qc_ok")


def _finais(day_dir: Path) -> list[dict]:
    p = day_dir / "finais.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _status_map(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    con = _db.connect(db_path)
    try:
        return {r["cut_id"]: r["status"]
                for r in con.execute("SELECT cut_id, status FROM cortes").fetchall()}
    finally:
        con.close()


def pendentes(day: str, factory_data: Path, db_path: Path) -> list[dict]:
    """Finais com status cut/qc_ok (aguardando o dono)."""
    st = _status_map(db_path)
    return [f for f in _finais(factory_data / day)
            if st.get(str(f.get("cut_id"))) in PENDENTE]


def marcar_qc_ok(db_path: Path, cut_ids: list[str]) -> None:
    con = _db.connect(db_path)
    try:
        for cid in cut_ids:
            con.execute("UPDATE cortes SET status='qc_ok' WHERE cut_id=? AND status='cut'",
                        (cid,))
        con.commit()
    finally:
        con.close()


def key_of_cut(day_dir: Path, cut_id: str) -> str | None:
    p = day_dir / "pack.json"
    if not p.exists():
        return None
    try:
        pack = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    for key, cred in (pack.get("creditos") or {}).items():
        if str((cred or {}).get("cut_id")) == cut_id:
            return key
    return None


def find_day_of_cut(factory_data: Path, cut_id: str, lookback: int = 7) -> str | None:
    """Acha o dia cujo pack.json contém o cut (botão não carrega a data)."""
    try:
        days = sorted([p for p in factory_data.iterdir() if p.is_dir()], reverse=True)
    except Exception:
        return None
    for d in days[:max(1, lookback)]:
        if key_of_cut(d, cut_id):
            return d.name
    return None


def aprovar(day: str, factory_data: Path, db_path: Path, cut_id: str,
            buffer_main=None) -> dict:
    """Agenda o corte aprovado no Buffer. Retorna resumo (nunca levanta)."""
    day_dir = factory_data / day
    st = _status_map(db_path).get(cut_id)
    if st not in (*PENDENTE, "aprovado"):
        return {"ok": False, "error": f"cut {cut_id} não está pendente (status={st})"}
    key = key_of_cut(day_dir, cut_id)
    if not key:
        return {"ok": False, "error": f"cut {cut_id} fora do pack"}
    try:
        from . import post_buffer as _pb
        rc = (buffer_main or _pb.main)(day, factory_data, only=[key])
    except Exception as exc:
        return {"ok": False, "error": f"Buffer falhou: {type(exc).__name__}: {str(exc)[:150]}"}
    if rc != 0:
        return {"ok": False, "error": f"Buffer retornou exit {rc} (ver buffer.json)"}
    con = _db.connect(db_path)
    try:
        con.execute("UPDATE cortes SET status='agendado' WHERE cut_id=?", (cut_id,))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "cut_id": cut_id, "key": key}


def rejeitar(db_path: Path, cut_id: str, motivo: str = "") -> dict:
    con = _db.connect(db_path)
    try:
        row = con.execute("SELECT cut_id FROM cortes WHERE cut_id=?", (cut_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": f"cut_id desconhecido: {cut_id}"}
        con.execute("UPDATE cortes SET status=? WHERE cut_id=?",
                    (f"rejeitado:{motivo}" if motivo else "rejeitado", cut_id))
        con.commit()
        return {"ok": True, "cut_id": cut_id}
    finally:
        con.close()


def preview_caption(corte: dict) -> str:
    titulo = str(corte.get("titulo") or "sem título")[:90]
    streamer = str(corte.get("streamer") or "?")
    views = corte.get("chat", "")
    return (f"🔍 PRÉVIA — tocar ✅ agenda, ❌ descarta\n"
            f"📌 {titulo}\n🎮 @{streamer} | sinal {views}\n"
            f"🆔 `{corte.get('cut_id')}`")


def enviar_previews(day: str, factory_data: Path, db_path: Path,
                    token: str = "", chat: str = "") -> dict:
    """Manda finais pendentes p/ o dono com botões ✅/❌. Retorna {enviados}. """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat or os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not (token and chat):
        return {"ok": False, "error": "sem TELEGRAM_BOT_TOKEN/OWNER"}
    api = f"https://api.telegram.org/bot{token}"
    s = requests.Session()
    enviados = 0
    for f in pendentes(day, factory_data, db_path):
        cid = str(f.get("cut_id"))
        kb = {"inline_keyboard": [[
            {"text": "✅ Aprovar", "callback_data": f"ap:{cid}"},
            {"text": "❌ Descartar", "callback_data": f"rj:{cid}"},
        ]]}
        try:
            with open(f["mp4"], "rb") as fh:
                def _do(_fh=fh):
                    r = s.post(f"{api}/sendVideo",
                               data={"chat_id": chat, "caption": preview_caption(f),
                                     "parse_mode": "Markdown",
                                     "reply_markup": json.dumps(kb)},
                               files={"video": (Path(f["mp4"]).name, _fh, "video/mp4")},
                               timeout=180)
                    r.raise_for_status()
                    return r.json()
                _net.call(_do)
            enviados += 1
        except Exception as exc:
            print(f"aprova: preview falhou {cid} ({type(exc).__name__})")
    return {"ok": True, "enviados": enviados}
