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
    """Finais com status cut/qc_ok (aguardando o dono).

    Sem arquivos do dia (runner efêmero): reconstrói da tabela previews
    (materializa mp4 do blob em temp). Temp é limpo após o envio.
    """
    import tempfile as _tf

    st = _status_map(db_path)
    arq = [f for f in _finais(factory_data / day)
           if st.get(str(f.get("cut_id"))) in PENDENTE]
    if arq:
        return arq
    out = []
    try:
        con = _db.connect(db_path)
        try:
            rows = con.execute("SELECT * FROM previews").fetchall()
        finally:
            try:
                con.close()
            except Exception:
                pass
    except Exception:
        return []
    for r in rows:
        d = dict(r)
        cid = str(d.get("cut_id") or "")
        if st.get(cid) not in PENDENTE:
            continue
        blob = d.get("mp4")
        if not blob or len(bytes(blob)) <= 100_000:
            continue
        try:
            tf = _tf.NamedTemporaryFile(suffix=".mp4", delete=False)
            tf.write(bytes(blob))
            tf.close()
            d["mp4"], d["_tmp"] = tf.name, True
            d["cut_id"] = cid
            out.append(d)
        except Exception:
            continue
    return out


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


def prev_row(db_path: Path, cut_id: str) -> dict | None:
    """Linha da tabela previews (fonte única; funciona sem arquivos)."""
    try:
        con = _db.connect(db_path)
    except Exception:
        return None
    try:
        try:
            row = con.execute("SELECT * FROM previews WHERE cut_id=?", (cut_id,)).fetchone()
        except Exception:
            return None
        if not row:
            return None
        d = dict(row)
        d.pop("mp4", None)
        return d
    finally:
        try:
            con.close()
        except Exception:
            pass


def find_day(db_path: Path, factory_data: Path, cut_id: str,
             lookback: int = 7) -> str | None:
    """Dia do cut: tabela previews primeiro (sem arquivos), pack depois."""
    r = prev_row(db_path, cut_id)
    if r and r.get("dia"):
        return str(r["dia"])
    return find_day_of_cut(factory_data, cut_id, lookback)


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


def _base_corte(factory_data: Path, db_path: Path, cut_id: str) -> tuple[str | None, dict, bool]:
    """(dia, corte, tem_arquivos): tabela previews primeiro, arquivos depois."""
    corte: dict = {}
    row = prev_row(db_path, cut_id)
    if row:
        tags = str(row.get("hashtags") or "").split()
        corte = {"cut_id": cut_id, "streamer": str(row.get("streamer") or ""),
                 "titulo": str(row.get("titulo") or ""),
                 "descricao": str(row.get("descricao") or ""),
                 "hashtags": tags, "url": str(row.get("url") or ""),
                 "jogo": str(row.get("jogo") or ""),
                 "views": 0, "duracao": 30.0}
        if row.get("dia"):
            return str(row["dia"]), corte, False
    day = find_day_of_cut(factory_data, cut_id)
    if not day:
        return None, corte, False
    day_dir = factory_data / day
    try:
        scored = json.loads((day_dir / "scored.json").read_text(encoding="utf-8"))
        finais = json.loads((day_dir / "finais.json").read_text(encoding="utf-8"))
    except Exception:
        return (day if corte else None), corte, False
    for lst in (finais, scored):
        for c in lst:
            if str(c.get("cut_id")) == cut_id:
                for k in ("titulo", "descricao", "hashtags", "streamer", "url", "jogo"):
                    if c.get(k) not in (None, ""):
                        corte[k if k != "titulo" else "titulo"] = c[k]
                corte["cut_id"] = cut_id
                if not corte.get("titulo"):
                    corte["titulo"] = str(c.get("titulo") or "")
                return day, corte, True
    return (day if corte else None), corte, bool(corte)


def _salvar_corte(factory_data: Path, db_path: Path, day: str | None, cut_id: str,
                  patch: dict, tem_arquivos: bool) -> str | None:
    """Aplica patch em tabela + arquivos (se houver) + pack + cortes + fila.
    Retorna status da fila (p/ aviso de agendado)."""
    import re as _re2

    if "descricao" in patch:
        patch["descricao"] = _re2.sub(r"https?://\S+", "",
                                      str(patch["descricao"] or "")).strip()[:500]
    if "titulo" in patch:
        patch["titulo"] = str(patch["titulo"] or "")[:90]
    if "jogo" in patch:
        patch["jogo"] = str(patch["jogo"] or "")[:60]
    con = _db.connect(db_path)
    try:
        _db.init_db(db_path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(previews)").fetchall()}
        if cols:
            sets = ", ".join(f"{k}=?" for k in patch if k in
                             {"titulo", "descricao", "hashtags", "jogo", "streamer", "url"})
            vals = [patch[k] if k != "hashtags" else " ".join(patch[k]) for k in patch
                    if k in {"titulo", "descricao", "hashtags", "jogo", "streamer", "url"}]
            if sets:
                try:
                    con.execute(f"UPDATE previews SET {sets} WHERE cut_id=?", (*vals, cut_id))
                except Exception:
                    pass
        try:
            if "titulo" in patch:
                con.execute("UPDATE cortes SET titulo=? WHERE cut_id=?", (patch["titulo"], cut_id))
            if "jogo" in patch:
                try:
                    con.execute("UPDATE cortes SET jogo=? WHERE cut_id=?", (patch["jogo"], cut_id))
                except Exception:
                    pass
        except Exception:
            pass
        fila_st = None
        try:
            row = con.execute("SELECT status FROM fila WHERE cut_id=?", (cut_id,)).fetchone()
            fila_st = row["status"] if row else None
        except Exception:
            pass
        con.commit()
    finally:
        try:
            con.close()
        except Exception:
            pass
    if tem_arquivos and day:
        from . import pack_redes as _pack

        day_dir = factory_data / day
        try:
            scored = json.loads((day_dir / "scored.json").read_text(encoding="utf-8"))
            finais = json.loads((day_dir / "finais.json").read_text(encoding="utf-8"))
            for lst in (scored, finais):
                for c in lst:
                    if str(c.get("cut_id")) == cut_id:
                        for k, v in patch.items():
                            c[k] = v
            (day_dir / "scored.json").write_text(
                json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
            (day_dir / "finais.json").write_text(
                json.dumps(finais, ensure_ascii=False, indent=1), encoding="utf-8")
            _pack.build_pack(day_dir, finais)
            if fila_st == "na_fila":
                pack_now = json.loads((day_dir / "pack.json").read_text(encoding="utf-8"))
                con2 = _db.connect(db_path)
                try:
                    for key, cred in (pack_now.get("creditos") or {}).items():
                        if str((cred or {}).get("cut_id")) == cut_id:
                            sets, vals = ["caption=?", "caption_tt=?"], [
                                str((pack_now.get("captions") or {}).get(key) or "")[:2100],
                                str((pack_now.get("captions_tt") or {}).get(key) or "")[:2100]]
                            if "titulo" in patch:
                                sets.append("titulo=?")
                                vals.append(patch["titulo"])
                            con2.execute(f"UPDATE fila SET {', '.join(sets)} WHERE cut_id=?",
                                         (*vals, cut_id))
                            break
                    con2.commit()
                except Exception:
                    pass
                finally:
                    try:
                        con2.close()
                    except Exception:
                        pass
        except Exception:
            pass
    return fila_st


def definir_titulo(factory_data: Path, db_path: Path, cut_id: str,
                   novo_titulo: str, model: str = "gemini-3.5-flash-lite",
                   api_key: str = "", gemini_fn=None) -> dict:
    """Título do dono vira base: IA refaz a descrição em cima dele.
    Funciona só com a tabela (sem arquivos). Nunca levanta.
    """
    from . import score as _score

    novo_titulo = (novo_titulo or "").strip()[:90]
    if not novo_titulo:
        return {"ok": False, "error": "título vazio"}
    day, base, tem_arq = _base_corte(factory_data, db_path, cut_id)
    if not day and not base.get("titulo") and not base.get("streamer"):
        return {"ok": False, "error": f"cut {cut_id} desconhecido"}
    refs: list[str] = []
    if tem_arq and day and cut_id.startswith("clip-"):
        try:
            clips = json.loads((factory_data / day / "clips.json").read_text(encoding="utf-8"))
            refs = [str(x.get("titulo_clip") or "") for x in clips
                    if not str(x.get("clip_id", "")).startswith(cut_id[5:])][:5]
        except Exception:
            refs = []
    leg = _score.legendar_clip({**base, "titulo_clip": novo_titulo},
                               model, api_key or os.environ.get("GEMINI_API_KEY", ""),
                               gemini_fn=gemini_fn, refs=refs)
    patch = {"titulo": novo_titulo,
             "descricao": str(leg.get("descricao") or f"@{base.get('streamer', '')}"),
             "hashtags": list(leg.get("hashtags") or [])}
    fila_st = _salvar_corte(factory_data, db_path, day, cut_id, patch, tem_arq)
    out = {"ok": True, "cut_id": cut_id, "titulo": novo_titulo,
           "descricao": patch["descricao"]}
    if fila_st == "agendado":
        out["aviso"] = "já agendado no Buffer — título novo vale pros próximos"
    return out


def definir_descricao(factory_data: Path, db_path: Path, cut_id: str,
                      nova_desc: str) -> dict:
    """Descrição escrita pelo dono (via `d:`). Vale p/ fila; agendado avisa."""
    nova_desc = (nova_desc or "").strip()
    if nova_desc.lower().startswith("d:"):
        nova_desc = nova_desc[2:].strip()
    nova_desc = nova_desc[:300]
    if not nova_desc:
        return {"ok": False, "error": "descrição vazia"}
    day, base, tem_arq = _base_corte(factory_data, db_path, cut_id)
    if not day and not base.get("streamer"):
        return {"ok": False, "error": f"cut {cut_id} desconhecido"}
    fila_st = _salvar_corte(factory_data, db_path, day, cut_id,
                            {"descricao": nova_desc}, tem_arq)
    out = {"ok": True, "cut_id": cut_id, "descricao": nova_desc}
    if fila_st == "agendado":
        out["aviso"] = "já agendado no Buffer — descrição nova vale pros próximos"
    return out


def definir_jogo(factory_data: Path, db_path: Path, cut_id: str,
                 nome: str) -> dict:
    """Dono informa o jogo na aprovação (VOD não tem fonte 100%).

    Funciona só com a tabela (sem arquivos). Snapshot da fila se na_fila.
    """
    nome = (nome or "").strip()[:60]
    if not nome:
        return {"ok": False, "error": "nome vazio"}
    day, base, tem_arq = _base_corte(factory_data, db_path, cut_id)
    if not day and not base.get("streamer"):
        # Tabela pode não ter o corte (fila antiga): registra o essencial.
        _db.init_db(db_path)
        con = _db.connect(db_path)
        try:
            con.execute("INSERT OR IGNORE INTO previews(cut_id, jogo) VALUES(?,?)",
                        (cut_id, nome))
            con.execute("UPDATE previews SET jogo=? WHERE cut_id=?", (nome, cut_id))
            con.commit()
        except Exception:
            pass
        finally:
            try:
                con.close()
            except Exception:
                pass
        return {"ok": True, "cut_id": cut_id, "jogo": nome}
    fila_st = _salvar_corte(factory_data, db_path, day, cut_id, {"jogo": nome}, tem_arq)
    out = {"ok": True, "cut_id": cut_id, "jogo": nome}
    if fila_st == "agendado":
        out["aviso"] = "já agendado — jogo vale pros próximos"
    return out


def parse_resposta(text: str) -> dict:
    """Uma resposta só com tudo: linhas `d:`/`jogo:` + resto = título.

    Ex:
      E morreu
      d: @alanzoka caiu do penhasco kkkk
      jogo: GTA V
    Retorna {titulo?, descricao?, jogo?} (só chaves presentes).
    """
    out: dict = {}
    resto: list[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("jogo:"):
            v = s[5:].strip()
            if v:
                out["jogo"] = v[:60]
        elif low.startswith("d:"):
            v = s[2:].strip()
            if v:
                out["descricao"] = v[:300]
        else:
            resto.append(s)
    t = " ".join(resto).strip()[:90]
    if t:
        out["titulo"] = t
    return out


def aplicar_resposta(factory_data: Path, db_path: Path, cut_id: str,
                     text: str, model: str = "gemini-3.5-flash-lite",
                     api_key: str = "", gemini_fn=None) -> dict:
    """Aplica título+descrição+jogo de uma vez (ordem: título→d:→jogo).

    Título sozinho refaz a descrição via IA; `d:` por cima preserva a sua.
    Nunca levanta em erro de parte: retorna o que aplicou + erros.
    """
    parts = parse_resposta(text)
    if not parts:
        return {"ok": False, "error": "resposta vazia"}
    out: dict = {"ok": True, "cut_id": cut_id, "aplicado": []}
    if "titulo" in parts:
        r = definir_titulo(factory_data, db_path, cut_id, parts["titulo"],
                           model, api_key, gemini_fn=gemini_fn)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error", "falha no título")}
        out["titulo"] = r["titulo"]
        out["descricao"] = r.get("descricao", "")  # IA; `d:` por cima se vier
        out["aplicado"].append("titulo")
        if r.get("aviso"):
            out.setdefault("avisos", []).append(r["aviso"])
    if "descricao" in parts:
        r = definir_descricao(factory_data, db_path, cut_id, parts["descricao"])
        if not r.get("ok"):
            out["ok"] = False
            out["error"] = r.get("error", "falha na descrição")
        else:
            out["descricao"] = r["descricao"]
            out["aplicado"].append("descricao")
            if r.get("aviso"):
                out.setdefault("avisos", []).append(r["aviso"])
    if "jogo" in parts:
        r = definir_jogo(factory_data, db_path, cut_id, parts["jogo"])
        if not r.get("ok"):
            out["ok"] = False
            out["error"] = r.get("error", "falha no jogo")
        else:
            out["jogo"] = r["jogo"]
            out["aplicado"].append("jogo")
            if r.get("aviso"):
                out.setdefault("avisos", []).append(r["aviso"])
    return out


def formatar_resposta(res: dict) -> str:
    """Confirmação única p/ Telegram após aplicar_resposta (puro, sem I/O)."""
    if not res.get("ok") and not res.get("aplicado"):
        return f"⚠️ {res.get('error', 'falha')}"
    lines = []
    if "titulo" in res:
        lines.append(f"✏️ título: {res['titulo']}")
    if res.get("descricao"):
        lines.append(f"📝 descrição: {str(res['descricao'])[:300]}")
    if "jogo" in res:
        lines.append(f"🎮 jogo: {res['jogo']}")
    msg = "\n".join(lines) if lines else "ok"
    for a in res.get("avisos") or []:
        msg += f"\n⚠️ {a}"
    if not (res.get("avisos")):
        msg += "\n\nToque ✅ na prévia p/ entrar na fila."
    return msg


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


SLOTS_DIA = 5


def comprometidos(db_path: Path, dia: str) -> int:
    """Cortes já donos de slot num dia (na fila + agendados)."""
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        row = con.execute(
            "SELECT COUNT(*) c FROM fila WHERE dia_alvo=? AND status IN ('na_fila','agendado')",
            (dia,)).fetchone()
        return int(row["c"] if row else 0)
    finally:
        con.close()


def proximo_slot(db_path: Path, hoje: str, agora_utc: str = "") -> tuple[str, int]:
    """Primeiro (dia, slot) livre e FUTURO — hoje cheio/passado, rola p/ amanhã+."""
    import datetime as _dt

    from config.settings import SLOTS_UTC

    base = _dt.date(int(hoje[:4]), int(hoje[5:7]), int(hoje[8:10]))
    try:
        agora = _dt.datetime.fromisoformat(agora_utc) if agora_utc else \
            _dt.datetime.now(_dt.timezone.utc)
    except ValueError:
        agora = _dt.datetime.now(_dt.timezone.utc)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=_dt.timezone.utc)
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        for d in range(15):
            dia = base + _dt.timedelta(days=d)
            usados = {r["slot"] for r in con.execute(
                "SELECT slot FROM fila WHERE dia_alvo=? AND status IN ('na_fila','agendado')",
                (dia.isoformat(),)).fetchall()}
            for s in range(SLOTS_DIA):
                if s in usados:
                    continue
                h, m = SLOTS_UTC[s % len(SLOTS_UTC)]
                due = _dt.datetime(dia.year, dia.month, dia.day, h, m,
                                   tzinfo=_dt.timezone.utc)
                if h == 0:
                    due += _dt.timedelta(days=1)
                if d == 0 and due <= agora + _dt.timedelta(minutes=15):
                    continue  # slot de hoje já passou: pula
                return dia.isoformat(), s
    finally:
        con.close()
    return (base + _dt.timedelta(days=14)).isoformat(), SLOTS_DIA - 1


def due_at(dia_alvo: str, slot: int) -> str:
    """ISO UTC do slot (9/12/15/18/21 BRT). Slot 0h cai no dia seguinte."""
    import datetime as _dt

    from config.settings import SLOTS_UTC

    h, m = SLOTS_UTC[slot % len(SLOTS_UTC)]
    base = _dt.date(int(dia_alvo[:4]), int(dia_alvo[5:7]), int(dia_alvo[8:10]))
    if h == 0:
        base += _dt.timedelta(days=1)
    return _dt.datetime(base.year, base.month, base.day, h, m,
                        tzinfo=_dt.timezone.utc).isoformat()


def enfileirar(day: str, factory_data: Path, db_path: Path, cut_id: str) -> dict:
    """Aprovação entra na fila (snapshot título/legenda/mp4). Rola de dia se cheio."""
    import datetime as _dt

    st = _status_map(db_path).get(cut_id)
    if st not in (*PENDENTE, "aprovado"):
        return {"ok": False, "error": f"cut {cut_id} não está pendente (status={st})"}
    day_dir = factory_data / day
    # Snapshot: tabela previews primeiro (nuvem não tem arquivos).
    prow = prev_row(db_path, cut_id)
    mp4 = titulo = cap = captt = url = ""
    if prow:
        mp4, titulo = str(prow.get("mp4") or ""), str(prow.get("titulo") or "")[:90]
        # mp4 blob não vem no prev_row: busca só o path p/ fila? fila não precisa
        # do path se o blob existir — promover lê o blob. Guarda marcador.
        cap, captt = str(prow.get("caption") or "")[:2100], str(prow.get("caption_tt") or "")[:2100]
        url = str(prow.get("url") or "")
    else:
        finais = {str(f.get("cut_id")): f for f in _finais(day_dir)}
        f = finais.get(cut_id)
        if not f:
            return {"ok": False, "error": f"cut {cut_id} fora dos finais"}
        key = key_of_cut(day_dir, cut_id)
        try:
            pack = json.loads((day_dir / "pack.json").read_text(encoding="utf-8"))
        except Exception:
            return {"ok": False, "error": "pack ilegível"}
        mp4, titulo = str(f.get("mp4") or ""), str(f.get("titulo") or "")[:90]
        cap = str((pack.get("captions") or {}).get(key or "", ""))[:2100]
        captt = str((pack.get("captions_tt") or {}).get(key or "", ""))[:2100]
        url = str(f.get("url") or "")
    dia_alvo, slot = proximo_slot(db_path, _dt.date.today().isoformat())
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        con.execute(
            "INSERT OR REPLACE INTO fila(cut_id, mp4, url, titulo, caption, caption_tt,"
            " dia_alvo, slot, status, criado_em) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (cut_id, mp4, url, titulo, cap, captt,
             dia_alvo, slot, "na_fila", _dt.date.today().isoformat()))
        con.execute("UPDATE cortes SET status='na_fila' WHERE cut_id=?", (cut_id,))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "cut_id": cut_id, "dia_alvo": dia_alvo, "slot": slot}


def promover_fila(factory_data: Path, db_path: Path, hoje: str = "",
                  channels_fn=None, create_fn=None, uploader=None) -> dict:
    """Agenda no Buffer tudo na fila com dia_alvo vencido. Retorna resumo."""
    import datetime as _dt

    from . import post_buffer as _pb
    from . import upload_public as _up

    hoje = hoje or _dt.date.today().isoformat()
    token = os.environ.get("BUFFER_API_KEY", "")
    if not token:
        return {"ok": False, "error": "sem BUFFER_API_KEY"}
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM fila WHERE status='na_fila' AND dia_alvo<=? ORDER BY dia_alvo, slot",
            (hoje,)).fetchall()]
    finally:
        con.close()
    if not rows:
        return {"ok": True, "agendados": 0}
    chans = (channels_fn or _pb.channels)(token)
    up = uploader or _up.upload
    ok, fail = 0, []
    for r in rows:
        mp4p = Path(str(r["mp4"] or ""))
        if mp4p.exists():
            url = up(mp4p)
        else:
            # Sem arquivo (nuvem): usa o blob da tabela previews.
            url = None
            try:
                conb = _db.connect(db_path)
                try:
                    brow = conb.execute("SELECT mp4 FROM previews WHERE cut_id=?",
                                        (r["cut_id"],)).fetchone()
                finally:
                    conb.close()
                blob = brow["mp4"] if brow else None
                if blob and len(bytes(blob)) > 100_000:
                    import tempfile as _tf
                    with _tf.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
                        tf.write(bytes(blob))
                    try:
                        url = up(Path(tf.name))
                    finally:
                        try:
                            Path(tf.name).unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception:
                url = None
        if not url:
            fail.append(r["cut_id"])
            continue
        due = due_at(r["dia_alvo"], int(r["slot"]))
        import datetime as _dt2
        if _dt2.datetime.fromisoformat(due) <= _dt2.datetime.now(_dt2.timezone.utc):
            nd, ns = proximo_slot(db_path, hoje)  # passou da hora: remaneja
            con0 = _db.connect(db_path)
            try:
                con0.execute("UPDATE fila SET dia_alvo=?, slot=? WHERE cut_id=?",
                             (nd, ns, r["cut_id"]))
                con0.commit()
            finally:
                con0.close()
            r["dia_alvo"], r["slot"] = nd, ns
            due = due_at(nd, ns)
        bom, pids = True, {}
        for svc in _pb.WANT:
            if svc not in chans:
                continue
            text = (r["caption_tt"] if svc == "tiktok" else r["caption"])[:2100]
            try:
                pids[svc] = (create_fn or _pb.create_post)(
                    token, svc, chans[svc], text, url,
                    due, r["titulo"] or f"ViraClipe {r['dia_alvo']}")
            except Exception:
                bom = False
        con = _db.connect(db_path)
        try:
            if bom:
                con.execute("UPDATE fila SET status='agendado' WHERE cut_id=?", (r["cut_id"],))
                con.execute("UPDATE cortes SET status='agendado' WHERE cut_id=?", (r["cut_id"],))
                for svc, pid in pids.items():
                    con.execute(
                        "INSERT OR REPLACE INTO posts(cut_id, rede, buffer_id, agendado_para)"
                        " VALUES(?,?,?,?)", (r["cut_id"], svc, pid, due))
                ok += 1
            else:
                fail.append(r["cut_id"])
            con.commit()
        finally:
            con.close()
    return {"ok": True, "agendados": ok, "falhas": fail}


def registrar_posts(day: str, factory_data: Path, db_path: Path) -> int:
    """Auto-post (fonte A) também ocupa slot: espelha pack+buffer na fila."""
    import datetime as _dt

    day_dir = factory_data / day
    try:
        pack = json.loads((day_dir / "pack.json").read_text(encoding="utf-8"))
        buf = json.loads((day_dir / "buffer.json").read_text(encoding="utf-8"))
    except Exception:
        return 0
    ok_keys = {r.get("key") for r in buf.get("posts", []) if r.get("id")}
    if not ok_keys:
        return 0
    _db.init_db(db_path)
    recs = [r for r in buf.get("posts", []) if r.get("id")]
    con = _db.connect(db_path)
    try:
        n = 0
        for key in sorted(ok_keys):
            cred = (pack.get("creditos") or {}).get(key) or {}
            cid = str(cred.get("cut_id") or "")
            if not cid:
                continue
            for r in recs:
                if r.get("key") == key:
                    con.execute(
                        "INSERT OR REPLACE INTO posts(cut_id, rede, buffer_id, agendado_para)"
                        " VALUES(?,?,?,?)",
                        (cid, str(r.get("svc") or ""), str(r.get("id") or ""),
                         str(r.get("due_at") or "")))
            try:
                slot = int(key[1:]) - 1
            except ValueError:
                slot = 0
            try:
                _fin = {str(x.get("cut_id")): x for x in json.loads(
                    (day_dir / "finais.json").read_text(encoding="utf-8"))}
            except Exception:
                _fin = {}
            con.execute(
                "INSERT OR REPLACE INTO fila(cut_id, mp4, url, titulo, caption, caption_tt,"
                " dia_alvo, slot, status, criado_em) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (cid, str((pack.get("videos") or {}).get(key) or ""),
                 str((_fin.get(cid) or {}).get("url") or ""),
                 str((pack.get("titles") or {}).get(key) or "")[:90],
                 str((pack.get("captions") or {}).get(key) or "")[:2100],
                 str((pack.get("captions_tt") or {}).get(key) or "")[:2100],
                 day, slot, "agendado", _dt.date.today().isoformat()))
            con.execute("UPDATE cortes SET status='agendado' WHERE cut_id=?", (cid,))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def preview_caption(corte: dict) -> str:
    titulo = str(corte.get("titulo") or "sem título")[:90]
    streamer = str(corte.get("streamer") or "?")
    views = corte.get("chat", "")
    return (f"🔍 PRÉVIA — ✅ fila, ❌ descarta\n"
            f"↩️ responda c/ título | `d:` descrição | `jogo:` nome do jogo\n"
            f"📌 {titulo}\n🎮 @{streamer} | sinal {views}\n"
            f"🆔 `{corte.get('cut_id')}`")


def _post_preview(s, api: str, chat: str, f: dict) -> dict:
    """Envia 1 prévia com botões. Retorna o JSON do Telegram."""
    cid = str(f.get("cut_id"))
    kb = {"inline_keyboard": [[
        {"text": "✅ Aprovar", "callback_data": f"ap:{cid}"},
        {"text": "❌ Descartar", "callback_data": f"rj:{cid}"},
    ]]}
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
        return _net.call(_do)


def _registrar_mapa(factory_data: Path, day: str, resps: list[tuple[str, dict]],
                    db_path: Path | None = None) -> None:
    mapa = {}
    for cid, resp in resps:
        try:
            fid = (((resp.get("result") or {}).get("video") or {})
                   .get("file_unique_id") or "")
            if fid:
                mapa[fid] = cid
        except Exception:
            pass
    if mapa:
        try:
            mp = factory_data / day
            prev = json.loads((mp / "preview_map.json").read_text(encoding="utf-8")) \
                if (mp / "preview_map.json").exists() else {}
            prev.update(mapa)
            (mp / "preview_map.json").write_text(
                json.dumps(prev, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    # Espelho no banco (nuvem efêmera perde o json).
    if mapa and db_path is not None:
        try:
            _db.init_db(db_path)
            con = _db.connect(db_path)
            try:
                for fid, cid in mapa.items():
                    con.execute("INSERT OR REPLACE INTO kv(chave, valor) VALUES(?,?)",
                                (f"pv:{fid}", cid))
                con.commit()
            finally:
                try:
                    con.close()
                except Exception:
                    pass
        except Exception:
            pass


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
    resps: list[tuple[str, dict]] = []
    for f in pendentes(day, factory_data, db_path):
        cid = str(f.get("cut_id"))
        try:
            resps.append((cid, _post_preview(s, api, chat, f)))
            enviados += 1
        except Exception as exc:
            print(f"aprova: preview falhou {cid} ({type(exc).__name__})")
        finally:
            try:
                if isinstance(f, dict) and f.get("_tmp"):
                    Path(str(f.get("mp4") or "")).unlink(missing_ok=True)
            except Exception:
                pass
    _registrar_mapa(factory_data, day, resps, db_path)
    return {"ok": True, "enviados": enviados}


def reenviar(factory_data: Path, db_path: Path, cut_id: str,
             token: str = "", chat: str = "") -> dict:
    """Manda a prévia de novo (perdeu o vídeo? edita melhor). Vale p/ fila tbm."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat or os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not (token and chat):
        return {"ok": False, "error": "sem TELEGRAM_BOT_TOKEN/OWNER"}
    day = find_day(db_path, factory_data, cut_id)
    if not day:
        return {"ok": False, "error": f"cut {cut_id} fora do pack"}
    f = next((x for x in _finais(factory_data / day)
              if str(x.get("cut_id")) == cut_id), None)
    if f and Path(str(f.get("mp4") or "")).exists():
        pass
    else:
        # Sem arquivo: reconstrói do blob da tabela.
        prow = prev_row(db_path, cut_id)
        if not prow:
            return {"ok": False, "error": f"cut {cut_id} desconhecido"}
        try:
            conb = _db.connect(db_path)
            try:
                brow = conb.execute("SELECT mp4 FROM previews WHERE cut_id=?",
                                    (cut_id,)).fetchone()
            finally:
                conb.close()
            blob = brow["mp4"] if brow else None
            if not blob or len(bytes(blob)) <= 100_000:
                return {"ok": False, "error": f"vídeo de {cut_id} sumiu do disco"}
            import tempfile as _tf
            tf = _tf.NamedTemporaryFile(suffix=".mp4", delete=False)
            tf.write(bytes(blob))
            tf.close()
            f = {**prow, "mp4": tf.name, "_tmp": True}
        except Exception:
            return {"ok": False, "error": f"vídeo de {cut_id} sumiu do disco"}
    try:
        resp = _post_preview(requests.Session(),
                             f"https://api.telegram.org/bot{token}", chat, f)
        _registrar_mapa(factory_data, day, [(cut_id, resp)], db_path)
        return {"ok": True, "cut_id": cut_id}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    finally:
        try:
            if isinstance(f, dict) and f.get("_tmp"):
                Path(str(f.get("mp4") or "")).unlink(missing_ok=True)
        except Exception:
            pass


def listar_fila(db_path: Path, dias: int = 7) -> list[dict]:
    """Aprovados na fila (p/ /lista e edição)."""
    import datetime as _dt

    _db.init_db(db_path)
    hoje = _dt.date.today().isoformat()
    con = _db.connect(db_path)
    try:
        return [dict(r) for r in con.execute(
            "SELECT cut_id, titulo, dia_alvo, slot, status FROM fila"
            " WHERE status IN ('na_fila','agendado') AND dia_alvo>=?"
            " ORDER BY dia_alvo, slot LIMIT 35", (hoje,)).fetchall()]
    finally:
        con.close()


def cut_por_titulo(factory_data: Path, titulo: str,
                   lookback: int = 7) -> str | None:
    """cut_id pela linha 📌 do caption (vale p/ prévias já enviadas)."""
    import re as _re

    t = _re.sub(r"[📌🔥]", "", titulo or "").strip().lower()
    if len(t) < 4:
        return None
    try:
        days = sorted([p for p in factory_data.iterdir() if p.is_dir()], reverse=True)
    except Exception:
        return None
    for d in days[:max(1, lookback)]:
        for name in ("finais.json", "scored.json"):
            p = d / name
            if not p.exists():
                continue
            try:
                items = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for c in (items if isinstance(items, list) else []):
                ct = str(c.get("titulo") or "").strip().lower()
                if ct and (ct in t or t in ct):
                    return str(c.get("cut_id"))
    return None


def cut_por_video(factory_data: Path, file_unique_id: str,
                  lookback: int = 7, db_path: Path | None = None) -> str | None:
    """cut_id pelo file_unique_id do vídeo respondido (robusto, sem caption)."""
    if not file_unique_id:
        return None
    if db_path is not None:
        try:
            con = _db.connect(db_path)
            try:
                row = con.execute("SELECT valor FROM kv WHERE chave=?",
                                  (f"pv:{file_unique_id}",)).fetchone()
            finally:
                try:
                    con.close()
                except Exception:
                    pass
            if row:
                return str(row["valor"])
        except Exception:
            pass
    try:
        days = sorted([p for p in factory_data.iterdir() if p.is_dir()], reverse=True)
    except Exception:
        return None
    for d in days[:max(1, lookback)]:
        p = d / "preview_map.json"
        if not p.exists():
            continue
        try:
            mapa = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if file_unique_id in mapa:
            return str(mapa[file_unique_id])
    return None
