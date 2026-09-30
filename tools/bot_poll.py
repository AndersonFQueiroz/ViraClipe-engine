"""Bot sem daemon: 1 passada de getUpdates -> processa -> sai.

Roda no GitHub Actions a cada 15 min (mirror público = minutos ilimitados).
 Cobre: botões ✅/❌/🎬, resposta c/ título, `d:` descrição, /lista,
 /pendentes, /status, /fila, /start, /help, /remover.
Sem dependência do python-telegram-bot: HTTP puro (requests).
Offset do getUpdates persiste no banco (tabela kv) — nunca repete update.
Uso: python3 tools/bot_poll.py [--once] (sempre once; loop é do cron)
Exit 0 sempre (falha parcial não quebra o schedule).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DB_PATH, FACTORY_DATA
from factory import aprova as _ap
from factory import db as _db
from factory import net as _net

import requests

API = ""
OWNER = ""


def api(method: str, **kwargs) -> dict:
    def _do():
        r = requests.post(f"{API}/{method}", timeout=60, **kwargs)
        r.raise_for_status()
        return r.json()

    try:
        return _net.call(_do)
    except Exception as exc:
        print(f"poll: {method} falhou ({type(exc).__name__})")
        return {}


def send_text(chat: str, text: str, kb: dict | None = None) -> None:
    payload = {"chat_id": chat, "text": text[:3500]}
    if kb:
        payload["reply_markup"] = json.dumps(kb)
    api("sendMessage", json=payload)


def get_offset() -> int:
    _db.init_db(DB_PATH)
    con = _db.connect(DB_PATH)
    try:
        row = con.execute("SELECT valor FROM kv WHERE chave='tg_offset'").fetchone()
        return int(row["valor"]) if row else 0
    except Exception:
        return 0
    finally:
        con.close()


def set_offset(off: int) -> None:
    con = _db.connect(DB_PATH)
    try:
        con.execute("INSERT OR REPLACE INTO kv(chave, valor) VALUES('tg_offset',?)",
                    (str(off),))
        con.commit()
    finally:
        con.close()


def _is_owner(uid) -> bool:
    return not OWNER or str(uid) == str(OWNER)


def handle_callback(q: dict) -> None:
    data, cqid = q.get("data") or "", q.get("id") or ""
    chat = str((((q.get("message") or {}).get("chat") or {}).get("id") or OWNER))
    api("answerCallbackQuery", json={"callback_query_id": cqid})
    uid = ((q.get("from") or {}).get("id"))
    if not _is_owner(uid):
        return
    if data.startswith("ap:"):
        cid = data[3:]
        day = _ap.find_day_of_cut(FACTORY_DATA, cid) or ""
        if not day:
            send_text(chat, f"⚠️ {cid} fora do pack.")
            return
        res = _ap.enfileirar(day, FACTORY_DATA, DB_PATH, cid)
        if not res.get("ok"):
            send_text(chat, f"⚠️ {res.get('error', 'falha')}")
            return
        promo = _ap.promover_fila(FACTORY_DATA, DB_PATH, day)
        try:
            from config.settings import SLOTS_UTC as _SL
            h, m = _SL[int(res.get("slot", 0)) % len(_SL)]
        except Exception:
            h, m = 12, 0
        send_text(chat, f"✅ na fila: {res.get('dia_alvo')} {h:02d}h{m:02d} "
                        f"(promo: {promo.get('agendados', 0)}).")
    elif data.startswith("rj:"):
        cid = data[3:]
        _ap.rejeitar(DB_PATH, cid)
        send_text(chat, f"❌ descartado {cid} (nunca posta).")
    elif data.startswith("ver:"):
        cid = data[4:]
        res = _ap.reenviar(FACTORY_DATA, DB_PATH, cid,
                           _api_token(), str(OWNER or chat))
        send_text(chat, "🎬 prévia reenviada 👆" if res.get("ok")
                  else f"⚠️ {res.get('error', 'falha')}")


def _api_token() -> str:
    return (API.rsplit("/bot", 1)[-1] if "/bot" in API else "")


def handle_message(m: dict) -> None:
    chat = str(((m.get("chat") or {}).get("id") or ""))
    uid = ((m.get("from") or {}).get("id"))
    text = (m.get("text") or "").strip()
    if not text or not _is_owner(uid):
        return
    if text.startswith("/"):
        cmd = text.split()[0].split("@")[0]
        arg = text[len(cmd):].strip()
        if cmd in ("/start", "/help", "/ajuda"):
            from bot.main import HELP_TXT  # noqa
            send_text(chat, HELP_TXT)
        elif cmd == "/status":
            from bot.main import status_text
            send_text(chat, status_text())
        elif cmd == "/fila":
            from bot.main import fila_text
            import datetime as _dt
            send_text(chat, fila_text(arg or _dt.date.today().isoformat()))
        elif cmd == "/pendentes":
            import datetime as _dt
            res = _ap.enviar_previews(arg or _dt.date.today().isoformat(),
                                      FACTORY_DATA, DB_PATH,
                                      _api_token(), chat)
            send_text(chat, f"prévias: {res}")
        elif cmd == "/lista":
            rows = _ap.listar_fila(DB_PATH)
            if not rows:
                send_text(chat, "fila vazia — aprove alguma prévia com ✅.")
                return
            lines, kb = [], []
            for r in rows[:15]:
                estado = "🕓" if r["status"] == "na_fila" else "📅"
                try:
                    from config.settings import SLOTS_UTC as _SL
                    h, mi = _SL[int(r["slot"]) % len(_SL)]
                except Exception:
                    h, mi = 12, 0
                lines.append(f"{estado} {str(r['dia_alvo'])[5:]} {h:02d}h{mi:02d} — "
                             f"{str(r['titulo'])[:45]}")
                kb.append([{"text": f"🎬 ver: {str(r['titulo'])[:25]}",
                            "callback_data": f"ver:{r['cut_id']}"[:64]}])
            send_text(chat, "\n".join(lines), {"inline_keyboard": kb})
        elif cmd == "/remover":
            from bot.main import parse_remover_args, apply_remover
            cut_id, motivo = parse_remover_args(arg)
            res = apply_remover(DB_PATH, cut_id, motivo)
            send_text(chat, res.get("error") or f"removido {res.get('cut_id')}.")
        return
    rep = m.get("reply_to_message") or {}
    cap = rep.get("caption") or ""
    if not cap:
        return
    mt = re.search(r"🆔 `([^`]+)`", cap)
    cid = mt.group(1) if mt else None
    if not cid and (rep.get("video") or {}).get("file_unique_id"):
        cid = _ap.cut_por_video(FACTORY_DATA, rep["video"]["file_unique_id"])
    if not cid:
        mt2 = re.search(r"📌 (.+)", cap)
        if mt2:
            cid = _ap.cut_por_titulo(FACTORY_DATA, mt2.group(1))
    if not cid:
        return
    if text.lower().startswith("d:"):
        res = _ap.definir_descricao(FACTORY_DATA, DB_PATH, cid, text[2:])
        send_text(chat, f"📝 descrição ok: {res.get('descricao', '')[:300]}"
                  if res.get("ok") else f"⚠️ {res.get('error', 'falha')}")
        return
    send_text(chat, "✏️ processando título + descrição...")
    res = _ap.definir_titulo(FACTORY_DATA, DB_PATH, cid, text)
    send_text(chat, f"✏️ título: {res.get('titulo')}\n📝 descrição: "
                    f"{res.get('descricao', '')[:300]}"
              if res.get("ok") else f"⚠️ {res.get('error', 'falha')}")


def main() -> int:
    global API, OWNER
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    OWNER = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not token:
        print("SEM TELEGRAM_BOT_TOKEN (exit 3).")
        return 3
    API = f"https://api.telegram.org/bot{token}"
    off = get_offset()
    try:
        data = api("getUpdates", json={"offset": off, "timeout": 50,
                                       "allowed_updates": ["message", "callback_query"]})
    except Exception:
        return 0
    updates = data.get("result") or []
    print(f"poll: {len(updates)} update(s) a partir de {off}.")
    for u in updates:
        try:
            if "callback_query" in u:
                handle_callback(u["callback_query"])
            elif "message" in u:
                handle_message(u["message"])
        except Exception as exc:
            print(f"poll: update {u.get('update_id')} falhou ({type(exc).__name__})")
        set_offset(int(u.get("update_id", off)) + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
