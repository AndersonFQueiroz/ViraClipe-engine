"""Bot Telegram do ViraClipe: monitor + takedown + GATE de aprovação.

Comandos:
  /start — ajuda
  /status — whitelist/denylist/vods/top cortes
  /fila [AAAA-MM-DD] — vods/scored/pack/buffer do dia
  /pendentes [AAAA-MM-DD] — reenvia prévias com botões ✅/❌ (só dono)
  /remover <cut_id> [motivo] — marca corte como removido + streamer na denylist (só dono)

Botões ✅/❌ nas prévias: aprovar agenda SÓ aquele corte no Buffer;
descartar marca rejeitado (nunca posta). Só OWNER decide.
Helpers puros não importam a lib do Telegram: testáveis sem rede.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from pathlib import Path

from config.settings import DB_PATH, FACTORY_DATA


def parse_remover_args(text: str) -> tuple[str, str]:
    parts = (text or "").split(None, 2)
    # "/remover cut_id motivo..." ou "cut_id motivo..."
    if parts and parts[0].startswith("/"):
        parts = parts[1:]
    cut_id = parts[0] if parts else ""
    motivo = parts[1] if len(parts) > 1 else ""
    return cut_id.strip(), motivo.strip()


def apply_remover(db_path: Path, cut_id: str, motivo: str = "") -> dict:
    """Marca corte removido + denylist do streamer. Retorna resumo."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT cut_id, video_id, streamer FROM cortes WHERE cut_id=?", (cut_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": f"cut_id desconhecido: {cut_id}"}
        streamer = str(row["streamer"])
        plats = [r["plataforma"] for r in
                 con.execute("SELECT DISTINCT plataforma FROM vods_processados WHERE video_id=?", (str(row["video_id"]),)).fetchall()]
        con.execute("UPDATE cortes SET status=? WHERE cut_id=?", (f"removido:{motivo}" if motivo else "removido", cut_id))
        for p in plats or ["twitch"]:
            con.execute(
                "INSERT INTO streamers(handle, plataforma, cortes_liberados, denylist) VALUES(?,?,0,1)"
                " ON CONFLICT(handle, plataforma) DO UPDATE SET denylist=1, cortes_liberados=0",
                (streamer, p),
            )
        con.commit()
        return {"ok": True, "cut_id": cut_id, "streamer": streamer, "motivo": motivo}
    finally:
        con.close()


def status_text(db_path: Path = DB_PATH) -> str:
    if not db_path.exists():
        return "sem banco ainda — rode run_diaria primeiro."
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        w = con.execute("SELECT COUNT(*) c FROM streamers WHERE cortes_liberados=1 AND denylist=0").fetchone()["c"]
        d = con.execute("SELECT COUNT(*) c FROM streamers WHERE denylist=1").fetchone()["c"]
        v = con.execute("SELECT COUNT(*) c FROM vods_processados").fetchone()["c"]
        lines = [f"whitelist: {w} | denylist: {d} | vods: {v}"]
        for r in con.execute("SELECT cut_id, streamer, score_final, status FROM cortes ORDER BY score_final DESC LIMIT 5"):
            lines.append(f"• {r['cut_id']} @{r['streamer']} {r['score_final']} [{r['status']}]")
        return "\n".join(lines)
    finally:
        con.close()


def fila_text(day: str, factory_data: Path = FACTORY_DATA) -> str:
    day_dir = factory_data / day
    parts = [f"fila {day}:"]
    for name in ("vods.json", "ingest.json", "candidatos.json", "scored.json", "cortes.json", "pack.json", "buffer.json"):
        p = day_dir / name
        if not p.exists():
            parts.append(f"• {name}: --")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            n = len(data) if isinstance(data, list) else len(data.get("posts", data.get("videos", {})))
            extra = ""
            if name == "buffer.json":
                extra = f" (ok={data.get('ok')} fail={data.get('fail')})"
            parts.append(f"• {name}: {n}{extra}")
        except Exception:
            parts.append(f"• {name}: ilegível")
    return "\n".join(parts)


def run() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    owner = os.environ.get("TELEGRAM_OWNER_CHAT_ID", "")
    if not token:
        print("SEM TELEGRAM_BOT_TOKEN — bot não iniciado (exit 3).")
        return 3
    from telegram import Update  # import tardio: helpers testam sem a lib
    from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                              ContextTypes)

    from factory import aprova as _ap

    def _is_owner(u: Update) -> bool:
        return not owner or str(u.effective_chat.id) == str(owner)

    async def _start(u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("ViraClipe monitor.\n/status\n/fila [AAAA-MM-DD]\n/pendentes [AAAA-MM-DD]\n/remover <cut_id> [motivo] (só dono)")

    async def _status(u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(status_text())

    async def _fila(u: Update, c: ContextTypes.DEFAULT_TYPE):
        day = (c.args[0] if c.args else _dt.date.today().isoformat())
        await u.message.reply_text(fila_text(day))

    async def _remover(u: Update, c: ContextTypes.DEFAULT_TYPE):
        if owner and str(u.effective_chat.id) != str(owner):
            await u.message.reply_text("apenas o dono pode remover.")
            return
        cut_id, motivo = parse_remover_args(" ".join(c.args or ""))
        if not cut_id:
            await u.message.reply_text("uso: /remover <cut_id> [motivo]")
            return
        res = apply_remover(DB_PATH, cut_id, motivo)
        if not res.get("ok"):
            await u.message.reply_text(res["error"])
            return
        await u.message.reply_text(
            f"removido {res['cut_id']} (@{res['streamer']} na denylist)."
            " Apague o post no Buffer/painel — o bot não deleta post publicado.")

    async def _pendentes(u: Update, c: ContextTypes.DEFAULT_TYPE):
        if not _is_owner(u):
            await u.message.reply_text("apenas o dono aprova.")
            return
        day = (c.args[0] if c.args else _dt.date.today().isoformat())
        res = _ap.enviar_previews(day, FACTORY_DATA, DB_PATH, token, str(u.effective_chat.id))
        await u.message.reply_text(f"prévias: {res}")

    async def _tap(u: Update, c: ContextTypes.DEFAULT_TYPE):
        q = u.callback_query
        await q.answer()
        if not _is_owner(u):
            await q.edit_message_caption(caption="apenas o dono aprova.")
            return
        data = (q.data or "")
        if data.startswith("ap:"):
            day = _ap.find_day_of_cut(FACTORY_DATA, data[3:]) or _dt.date.today().isoformat()
            cid = data[3:]
            res = _ap.aprovar(day, FACTORY_DATA, DB_PATH, cid)
            if res.get("ok"):
                await q.edit_message_caption(caption=f"✅ AGENDADO {cid} (slot {res.get('key')}).")
            else:
                await q.edit_message_caption(caption=f"⚠️ {res.get('error', 'falha')}")
        elif data.startswith("rj:"):
            cid = data[3:]
            _ap.rejeitar(DB_PATH, cid)
            await q.edit_message_caption(caption=f"❌ descartado {cid} (nunca posta).")

    async def _daily(ctx: ContextTypes.DEFAULT_TYPE):
        """Cron interno 08h BRT: roda tools/dia.py num thread e avisa o dono."""
        import subprocess as _sp
        import threading as _th

        import requests as _rq

        def _run():
            try:
                r = _sp.run(["python3", "tools/dia.py", "--max", "5"],
                            capture_output=True, text=True, timeout=7200)
                tail = (r.stdout or "")[-1200:]
                status = "ok" if r.returncode == 0 else f"exit {r.returncode}"
            except Exception as exc:
                tail, status = f"{type(exc).__name__}: {exc}"[:300], "falha"
            try:
                _rq.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         json={"chat_id": owner,
                               "text": f"⏰ dia automático: {status}\n{tail[-1000:]}"},
                         timeout=30)
            except Exception:
                pass

        _th.Thread(target=_run, daemon=True).start()
        await ctx.bot.send_message(chat_id=owner, text="⏰ dia automático iniciado.")

    app = Application.builder().token(token).build()
    if os.environ.get("VIRACLIP_DAILY", "") == "1" and owner:
        try:
            from datetime import time as _time
            from zoneinfo import ZoneInfo as _ZI
            app.job_queue.run_daily(_daily, time=_time(8, 0, tzinfo=_ZI("America/Sao_Paulo")),
                                    name="viraclipe-dia")
            print("Cron interno ativo: dia.py todo dia 08h BRT.")
        except Exception as exc:
            print(f"cron interno off ({type(exc).__name__})")
    app.add_handler(CommandHandler("start", _start))
    app.add_handler(CommandHandler("status", _status))
    app.add_handler(CommandHandler("fila", _fila))
    app.add_handler(CommandHandler("pendentes", _pendentes))
    app.add_handler(CallbackQueryHandler(_tap))
    app.add_handler(CommandHandler("remover", _remover))
    print("Bot ViraClipe no ar (polling).")
    app.run_polling()
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
