"""Longos 10+ min (YouTube): clipe -> VOD em volta -> render 16:9 -> thumb.

Fluxo (gate no Telegram, nada agenda sem o dono):
1. escolhe clipe Twitch ainda NÃO usado em short;
2. baixa só a janela do VOD (pad 4 min, estende até 10:00, máx 15:00);
3. rende 16:9 720p com marca d'água;
4. monta a thumb-base 1280x720 (3 frames + rosto, sem texto);
5. manda a thumb-base + prévia de 10 min no Telegram;
6. dono responde com o texto/título/descrição; bot compõe a thumb final;
7. ✅ no Telegram cria o post no YouTube (Buffer) com thumbnailUrl.

3 por dia, encaixados entre os 5 shorts (UTC 13:30/16:30/19:30).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from config.settings import (DB_PATH, FACTORY_DATA, LONGO_ALVO, LONGO_MAX,
                             LONGO_MAX_DIA, LONGO_MIN_VIEWS, LONGO_PAD,
                             LONGO_SLOTS_UTC, LONGO_THUMB_ESTILO, ROOT)
from . import clips as _clips
from . import db as _db
from . import net as _net
from . import post_buffer as _buf
from . import render as _render
from . import upload_public

THUMB_W, THUMB_H = 1280, 720
_THUMB_FONT = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
_YELLOW = (255, 214, 0)
_WHITE = (245, 245, 245)
_ID_RE = re.compile(r"🆔\s*(l[0-9a-f]{10})\b")
_LABEL_RE = re.compile(r"^\s*(thumb|t[ií]tulo|desc(?:ri[cç][aã]o)?)\s*:\s*(.*)$", re.I)


def _log(msg: str) -> None:
    print(f"[longos] {msg}", flush=True)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        p = ROOT / ".env"
        if p.exists():
            load_dotenv(p)
    except Exception:
        pass


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _today() -> str:
    return _now().date().isoformat()


def longo_id(clip_id: str) -> str:
    return "l" + hashlib.sha1((clip_id or "").encode("utf-8")).hexdigest()[:10]


def janela(anchor: float, clip_dur: float = 30.0, vod_dur: float = 0.0,
           alvo: int | None = None, pad: int | None = None,
           maximo: int | None = None) -> tuple[float, float, float] | None:
    """Janela de 10 min em volta do clipe; None se o VOD não tiver material."""
    alvo = int(alvo or LONGO_ALVO)
    pad = int(pad or LONGO_PAD)
    maximo = int(maximo or LONGO_MAX)
    if vod_dur and float(vod_dur) < alvo:
        return None
    anchor = max(0.0, float(anchor))
    clip_dur = max(1.0, float(clip_dur or 1.0))
    if vod_dur:
        anchor = min(anchor, max(0.0, float(vod_dur) - clip_dur))
    start = max(0.0, anchor - pad)
    end = anchor + clip_dur + pad
    if vod_dur:
        end = min(end, float(vod_dur))
    falta = alvo - (end - start)
    if falta > 0:
        add = min(falta / 2.0, start)
        start -= add
        falta -= add
        if falta > 0:
            room = (float(vod_dur) - end) if vod_dur else falta
            add = min(falta, max(0.0, room))
            end += add
            falta -= add
        if falta > 0:
            add = min(falta, start)
            start -= add
            falta -= add
    if end - start < alvo:
        return None
    if end - start > maximo:
        start = max(0.0, anchor - (maximo - clip_dur) / 2.0)
        end = start + maximo
        if vod_dur and end > float(vod_dur):
            end = float(vod_dur)
            start = max(0.0, end - maximo)
    if end - start < alvo:
        return None
    return round(start, 2), round(end, 2), round(end - start, 2)


def parse_texto(text: str) -> dict:
    """Aceita `thumb:`/`titulo:`/`desc:` (multi-linha) ou texto puro = thumb."""
    out: dict[str, str] = {}
    key, buf = "", []
    for line in (text or "").splitlines():
        m = _LABEL_RE.match(line)
        if m:
            if key:
                out[key] = "\n".join(buf).strip()
            raw = m.group(1).lower()
            key = "thumb" if raw.startswith("thumb") else (
                "titulo" if raw.startswith("t") else "desc")
            buf = [m.group(2)]
        elif key:
            buf.append(line)
        else:
            buf.append(line)
    if key:
        out[key] = "\n".join(buf).strip()
    if not out and (text or "").strip():
        out["thumb"] = text.strip()
    return out


def proximo_slot_longo(db_path: Path = DB_PATH,
                       agora: _dt.datetime | None = None) -> str:
    """Próximo slot UTC livre (3/dia) entre os 5 shorts."""
    agora = agora or _now()
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        rows = con.execute(
            "SELECT due_at FROM longos WHERE status IN ('aprovado','agendado')"
            " AND due_at != ''").fetchall()
    finally:
        con.close()
    ocupados = {str(r["due_at"]) for r in rows}
    for d in range(0, 10):
        dia = agora.date() + _dt.timedelta(days=d)
        for h, m in LONGO_SLOTS_UTC:
            dt = _dt.datetime(dia.year, dia.month, dia.day, h, m,
                              tzinfo=_dt.timezone.utc)
            if dt <= agora + _dt.timedelta(minutes=10):
                continue
            iso = dt.isoformat()
            if iso not in ocupados:
                return iso
    return ""


def due_brt(iso: str) -> str:
    try:
        dt = _dt.datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        brt = dt.astimezone(_dt.timezone(_dt.timedelta(hours=-3)))
        return brt.strftime("%d/%m %H:%M BRT")
    except Exception:
        return iso


def _row(db_path: Path, longo: str) -> dict | None:
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        r = con.execute("SELECT * FROM longos WHERE longo_id=?", (longo,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def _por_clip(db_path: Path, clip_id: str) -> dict | None:
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        r = con.execute("SELECT * FROM longos WHERE clip_id=?", (clip_id,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def _salvar(db_path: Path, row: dict) -> None:
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(longos)").fetchall()]
        keys = [k for k in row if k in cols]
        con.execute(
            f"INSERT OR REPLACE INTO longos({','.join(keys)}) "
            f"VALUES({','.join('?' for _ in keys)})",
            [row[k] for k in keys])
        con.commit()
    finally:
        con.close()


def _update(db_path: Path, longo: str, **fields) -> None:
    if not fields:
        return
    _db.init_db(db_path)
    con = _db.connect(db_path)
    try:
        sets = ",".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE longos SET {sets} WHERE longo_id=?",
                    [*fields.values(), longo])
        con.commit()
    finally:
        con.close()


def _vod_duracao(url: str, runner=subprocess.run) -> float:
    try:
        r = runner(["yt-dlp", "--no-warnings", "--skip-download",
                    "--print", "%(duration)s", url],
                   capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            return float(str(r.stdout or "").strip().splitlines()[-1])
    except Exception:
        pass
    return 0.0


def _hms(seg: float) -> str:
    s = int(max(0, seg))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def baixar_trecho(vod_url: str, start: float, end: float, out_mp4: Path,
                  runner=subprocess.run) -> bool:
    if out_mp4.exists() and out_mp4.stat().st_size > 100_000:
        return True
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist",
           "-f", "bv*[height<=720]+ba/b[height<=720]/b",
           "--download-sections", f"*{_hms(start)}-{_hms(end)}",
           "--force-keyframes-at-cuts", "--merge-output-format", "mp4",
           "-o", str(out_mp4), vod_url]
    try:
        _log(f"baixando {_hms(start)}-{_hms(end)} do VOD...")
        r = runner(cmd, capture_output=True, text=True, timeout=1800)
        ok = r.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 100_000
        if not ok:
            _log(f"download falhou: {str(getattr(r, 'stderr', '') or '')[-200:]}")
        return ok
    except Exception as exc:
        _log(f"download erro: {type(exc).__name__}")
        return False


def _duracao_mp4(path: Path, runner=subprocess.run) -> float:
    try:
        r = runner(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", str(path)],
                   capture_output=True, text=True, timeout=60)
        return float(str(r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def render_longo(src: Path, out: Path, duracao: int | None = None,
                 runner=subprocess.run) -> bool:
    if out.exists() and out.stat().st_size > 100_000:
        return True
    font = _render._font()
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1")
    if font:
        vf += "," + _render.build_overlay_vf_169(font)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src), "-t", str(int(duracao or LONGO_ALVO)),
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    try:
        _log("rendendo 16:9 720p...")
        r = runner(cmd, capture_output=True, text=True, timeout=1800)
        ok = r.returncode == 0 and out.exists() and out.stat().st_size > 100_000
        if not ok:
            _log(f"render falhou: {str(getattr(r, 'stderr', '') or '')[-200:]}")
        return ok
    except Exception as exc:
        _log(f"render erro: {type(exc).__name__}")
        return False


def gerar_preview(final: Path, out: Path, runner=subprocess.run) -> bool:
    """Proxy 480p <50MB p/ Telegram (o post usa o 720p no host)."""
    if out.exists() and out.stat().st_size > 100_000:
        return True
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(final), "-vf", "scale=-2:480",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
           "-maxrate", "560k", "-bufsize", "1120k",
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)]
    try:
        _log("gerando preview 480p...")
        r = runner(cmd, capture_output=True, text=True, timeout=1800)
        ok = r.returncode == 0 and out.exists() and out.stat().st_size > 50_000
        if ok and out.stat().st_size > 49_000_000:
            _log("preview >49MB — reduzindo")
            r2 = runner(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                         "-i", str(final), "-vf", "scale=-2:360",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
                         "-maxrate", "420k", "-bufsize", "840k",
                         "-c:a", "aac", "-b:a", "56k",
                         "-movflags", "+faststart", str(out)],
                        capture_output=True, text=True, timeout=1800)
            ok = r2.returncode == 0 and out.exists() and out.stat().st_size > 50_000
        return ok
    except Exception as exc:
        _log(f"preview erro: {type(exc).__name__}")
        return False


def _frame(src: Path, t: float, out: Path, runner=subprocess.run) -> bool:
    try:
        r = runner(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{max(0.0, t):.2f}", "-i", str(src),
                    "-frames:v", "1", "-q:v", "2", str(out)],
                   capture_output=True, text=True, timeout=120)
        return r.returncode == 0 and out.exists() and out.stat().st_size > 5_000
    except Exception:
        return False


def _rounded_mask(size: tuple[int, int], radius: int):
    from PIL import Image, ImageDraw

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def _facecam_panel(face_frame: Path, panel_w=360, panel_h=236):
    from PIL import Image, ImageOps

    im = Image.open(face_frame).convert("RGB")
    w, h = im.size
    crop = im.crop((0, 0, min(300, w), min(200, h)))
    panel = ImageOps.fit(crop, (panel_w, panel_h))
    border, radius = 8, 22
    out = Image.new("RGBA", (panel_w + 2 * border, panel_h + 2 * border),
                    (0, 0, 0, 0))
    frame = Image.new("RGBA", out.size, _YELLOW + (255,))
    out.paste(frame, (0, 0), _rounded_mask(out.size, radius + border))
    out.paste(panel.convert("RGBA"), (border, border),
              _rounded_mask((panel_w, panel_h), radius))
    return out


def montar_thumb_base(frames: list[Path], face_frame: Path, face_box,
                      out_jpg: Path, estilo: str = "clean") -> bool:
    """1280x720 sem texto: frame do jogo inteiro + texto à esquerda.

    `estilo="facecam"` recorta o canto superior esquerdo (facecam do streamer)
    num painel arredondado à direita; `clean` usa só o jogo (universal).
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    try:
        src = face_frame if Path(face_frame).exists() else frames[0]
        canvas = ImageOps.fit(Image.open(src).convert("RGB"),
                              (THUMB_W, THUMB_H)).convert("RGBA")
        canvas = Image.alpha_composite(
            canvas, Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 18)))

        over = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for y in range(280, THUMB_H):
            a = int((y - 280) / (THUMB_H - 280) * 235)
            d.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, min(240, a)))
        canvas = Image.alpha_composite(canvas, over)

        if estilo == "facecam":
            blur = canvas.crop((0, 0, 300, 200)).filter(
                ImageFilter.GaussianBlur(18))
            canvas.paste(blur, (0, 0))
            panel = _facecam_panel(face_frame)
            px = THUMB_W - panel.width - 36
            py = (THUMB_H - panel.height) // 2
            canvas.paste(panel, (px, py), panel)

        canvas.convert("RGB").save(out_jpg, "JPEG", quality=93, optimize=True)
        return out_jpg.exists() and out_jpg.stat().st_size > 20_000
    except Exception as exc:
        _log(f"thumb base erro: {type(exc).__name__}: {exc}")
        return False


def _wrap(draw, texto: str, font, max_w: float) -> list[str]:
    linhas = [ln for ln in texto.splitlines() if ln.strip()] or [texto.strip()]
    out: list[str] = []
    for ln in linhas:
        palavras = ln.split()
        if not palavras:
            continue
        cur = palavras[0]
        for p in palavras[1:]:
            teste = f"{cur} {p}"
            if draw.textlength(teste, font=font) <= max_w:
                cur = teste
            else:
                out.append(cur)
                cur = p
        out.append(cur)
    return out or [texto.strip()]


def render_thumb_texto(base_jpg: Path, texto: str, out_jpg: Path,
                       max_w: int = 820) -> bool:
    """Compõe o texto do dono na thumb-base (branco + última linha amarela)."""
    from PIL import Image, ImageDraw, ImageFont

    texto = (texto or "").strip()
    try:
        base = Image.open(base_jpg).convert("RGB")
    except Exception:
        return False
    if not texto:
        base.save(out_jpg, "JPEG", quality=92, optimize=True)
        return out_jpg.exists()
    font_path = str(_THUMB_FONT) if _THUMB_FONT.exists() else (
        _render._font() or "")
    if not font_path:
        return False
    draw = ImageDraw.Draw(base)
    max_h = 470
    chosen = None
    for size in range(176, 59, -6):
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            return False
        lines = _wrap(draw, texto.upper(), font, max_w)
        line_h = int(size * 1.0)
        if len(lines) <= 3 and len(lines) * line_h <= max_h and all(
                draw.textlength(ln, font=font) <= max_w for ln in lines):
            chosen = (font, lines, line_h, size)
            break
    if chosen is None:
        size = 64
        font = ImageFont.truetype(font_path, size)
        chosen = (font, _wrap(draw, texto.upper(), font, max_w)[:3], size, size)
    font, lines, line_h, size = chosen
    total_h = len(lines) * line_h
    y = THUMB_H - 34 - total_h
    x = 44
    stroke = max(5, int(size * 0.075))
    for i, ln in enumerate(lines):
        fill = _YELLOW if i == len(lines) - 1 else _WHITE
        draw.text((x + 4, y + i * line_h + 5), ln, font=font,
                  fill=(0, 0, 0), stroke_width=stroke, stroke_fill=(0, 0, 0))
        draw.text((x, y + i * line_h), ln, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
    base.save(out_jpg, "JPEG", quality=92, optimize=True)
    return out_jpg.exists()


def _upload_imagem(path: Path) -> str:
    blob = path.read_bytes()
    for url, data in (
        ("https://catbox.moe/user/api.php", {"reqtype": "fileupload"}),
        ("https://litterbox.catbox.moe/resources/internals/api.php",
         {"reqtype": "fileupload", "time": "72h"}),
    ):
        try:
            r = _net.post(requests.Session(), url,
                          files={"fileToUpload": (path.name, blob, "image/jpeg")},
                          data=data, timeout=180)
            body = str(r.text or "").strip()
            if body.startswith("https://"):
                return body
        except Exception:
            continue
    return ""


def _tg() -> tuple[str, str]:
    return (os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            os.environ.get("TELEGRAM_OWNER_CHAT_ID", ""))


def _tg_post(url: str, data: dict, files: dict, timeout: int = 300) -> dict:
    r = requests.post(url, data=data, files=files, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _send_photo(api: str, chat: str, jpg: Path, caption: str,
                kb: dict | None = None) -> dict:
    blob = jpg.read_bytes()
    data = {"chat_id": chat, "caption": caption[:1024]}
    if kb:
        data["reply_markup"] = json.dumps(kb)
    return _tg_post(f"{api}/sendPhoto", data,
                    {"photo": (jpg.name, blob, "image/jpeg")}, timeout=180)


def _send_video(api: str, chat: str, mp4: Path, caption: str,
                kb: dict | None = None) -> dict:
    blob = mp4.read_bytes()
    data = {"chat_id": chat, "caption": caption[:1024],
            "supports_streaming": "true"}
    if kb:
        data["reply_markup"] = json.dumps(kb)
    return _tg_post(f"{api}/sendVideo", data,
                    {"video": (mp4.name, blob, "video/mp4")}, timeout=600)


def _titulo(p: dict) -> str:
    clip = re.sub(r"^\s*\d+\s*/\s*", "", str(p.get("titulo_clip") or "")).strip()
    jogo = str(p.get("jogo") or "").strip()
    base = f"{str(p.get('streamer') or '').upper()} JOGANDO {jogo.upper()}"
    if clip:
        base += f": {clip}"
    return base[:95]


def _descricao(p: dict) -> str:
    streamer = str(p.get("streamer") or "")
    jogo = str(p.get("jogo") or "")
    linhas = [f"@{streamer} jogando {jogo} ao vivo na Twitch.", "",
              "Canal @viraclipe.oficial — cortes diários dos maiores streamers."]
    return "\n".join(linhas)[:2000]


def enviar_previews(row: dict, base_jpg: Path, preview_mp4: Path,
                    exemplo: str = "", db_path: Path = DB_PATH) -> dict:
    token, chat = _tg()
    if not (token and chat):
        return {"ok": False, "error": "sem TELEGRAM_BOT_TOKEN/OWNER"}
    api = f"https://api.telegram.org/bot{token}"
    lid = str(row["longo_id"])
    clip = str(row.get("titulo_clip") or "").strip()
    try:
        base_cap = (
            "🖼️ THUMB BASE — responda ESTA foto com o texto\n"
            "Ex.: thumb: NÃO É POSSÍVEL KKKKKKKK\n"
            "Opcional: titulo: ... / desc: ...\n"
            + (f"🎞️ Clipe original: {clip[:150]}\n" if clip else "")
            + f"📌 Título sugerido: {str(row.get('titulo') or '')[:90]}\n"
            f"🎮 @{row.get('streamer')} | {row.get('jogo')}\n"
            f"🆔 {lid}")
        b = _send_photo(api, chat, base_jpg, base_cap,
                        {"inline_keyboard": [[{"text": "✅ Usar sem texto",
                                               "callback_data": f"ltb:{lid}"}]]})
        bm = ((b.get("result") or {}).get("message_id")) or 0
        _update(db_path, lid, thumb_msg_id=int(bm))
    except Exception as exc:
        return {"ok": False, "error": f"thumb base: {type(exc).__name__}"}
    try:
        video_cap = (
            "🎬 LONGO 10 min — prévia (o post usa 720p)\n"
            + (f"🎞️ Clipe original: {clip[:150]}\n" if clip else "")
            + f"📌 Título sugerido: {str(row.get('titulo') or '')[:90]}\n"
            f"🎮 @{row.get('streamer')} | {row.get('jogo')}\n"
            "👉 o ✅ fica na THUMB FINAL (responda a foto base)\n"
            f"🆔 {lid}")
        v = _send_video(api, chat, preview_mp4, video_cap,
                        {"inline_keyboard": [[{"text": "❌ Descartar",
                                               "callback_data": f"lvr:{lid}"}]]})
        res = v.get("result") or {}
        fid = str((res.get("video") or {}).get("file_id") or "")
        mid = int(res.get("message_id") or 0)
        _update(db_path, lid, preview_file_id=fid, preview_msg_id=mid,
                status="pendente")
    except Exception as exc:
        return {"ok": False, "error": f"vídeo: {type(exc).__name__}"}
    if exemplo:
        try:
            ex_jpg = preview_mp4.parent / f"thumb-exemplo-{lid}.jpg"
            if render_thumb_texto(base_jpg, exemplo, ex_jpg):
                url = _upload_imagem(ex_jpg)
                _update(db_path, lid, thumb_texto=exemplo, thumb_url=url)
                _send_photo(api, chat, ex_jpg,
                            "🖼️ EXEMPLO de thumb com texto (o texto final é o "
                            f"que você mandar)\n🆔 {lid}")
        except Exception as exc:
            _log(f"exemplo falhou: {type(exc).__name__}")
    return {"ok": True}


def _render_base(row: dict, src: Path, anchor_off: float,
                 out_dir: Path) -> tuple[Path, object] | None:
    dur = _duracao_mp4(src)
    if dur <= 0:
        return None
    lid = str(row["longo_id"])
    frame = out_dir / f"frame-{lid}.jpg"
    if not _frame(src, anchor_off, frame):
        return None
    base = out_dir / f"thumb-base-{lid}.jpg"
    if not montar_thumb_base([frame], frame, None, base,
                             estilo=LONGO_THUMB_ESTILO):
        return None
    return base, None


def _candidato(c: dict) -> dict:
    return {
        "clip_id": c.get("clip_id", ""),
        "streamer": c.get("streamer", ""),
        "titulo_clip": c.get("titulo_clip", ""),
        "duracao": float(c.get("duracao") or 0),
        "views": int(c.get("views") or 0),
        "vod_id": str(c.get("vod_id") or ""),
        "vod_offset": float(c.get("vod_offset") or -1),
        "jogo": c.get("jogo", ""),
        "url": c.get("url", ""),
        "vod_url": (f"https://www.twitch.tv/videos/{c.get('vod_id')}"
                    if c.get("vod_id") else ""),
    }


def selecionar_candidatos(day: str, db_path: Path = DB_PATH,
                          max_n: int = 3, fetch_fn=None,
                          min_views: int | None = None) -> list[dict]:
    """Clips novos (não usados em short/longo), 1 por streamer, top views."""
    _db.init_db(db_path)
    min_views = LONGO_MIN_VIEWS if min_views is None else min_views
    tw_id = os.environ.get("TWITCH_CLIENT_ID", "")
    tw_sec = os.environ.get("TWITCH_CLIENT_SECRET", "")
    fetch = fetch_fn or (lambda h: _clips.fetch_clips(
        h, tw_id, tw_sec, days=14, first=100))
    con = _db.connect(db_path)
    try:
        whitelist = [dict(r) for r in con.execute(
            "SELECT handle FROM streamers WHERE plataforma='twitch'"
            " AND cortes_liberados=1 AND denylist=0 ORDER BY handle").fetchall()]
        vistos = {str(r[0]) for r in con.execute(
            "SELECT clip_id FROM clips_vistos").fetchall()}
        usados = {str(r[0]) for r in con.execute(
            "SELECT video_id FROM cortes").fetchall()}
        usados |= {str(r[0]) for r in con.execute(
            "SELECT clip_id FROM longos").fetchall()}
        recentes: set[str] = set()
        for r in con.execute("SELECT streamer, dia FROM longos"
                             " WHERE status != 'rejeitado'").fetchall():
            try:
                d = (_dt.date.fromisoformat(day)
                     - _dt.date.fromisoformat(str(r["dia"])[:10])).days
            except ValueError:
                continue
            if d < 7:
                recentes.add(str(r["streamer"]))
    finally:
        con.close()
    cands: list[dict] = []
    for s in whitelist:
        handle = str(s["handle"])
        if handle in recentes:
            continue
        try:
            clips = fetch(handle) or []
        except Exception:
            continue
        best = None
        for c in clips:
            cid = str(c.get("clip_id") or "")
            if not cid or cid in vistos:
                continue
            if cid in usados or f"clip:{cid}" in usados:
                continue
            if float(c.get("duracao") or 0) < 15:
                continue
            if float(c.get("vod_offset") or -1) < 0:
                continue
            if not str(c.get("vod_id") or ""):
                continue
            if int(c.get("views") or 0) < min_views:
                continue
            if best is None or int(c.get("views") or 0) > int(best.get("views") or 0):
                best = c
        if best:
            cands.append(_candidato(best))
    cands.sort(key=lambda c: c["views"], reverse=True)
    return cands[:max(1, max_n * 3)]


def _registrar_clip_visto(db_path: Path, cand: dict) -> None:
    con = _db.connect(db_path)
    try:
        _clips.register_clip(con, {
            "clip_id": cand["clip_id"], "streamer": cand["streamer"],
            "vod_id": cand["vod_id"], "vod_offset": cand["vod_offset"],
            "views": cand["views"], "titulo_clip": cand["titulo_clip"],
        })
        con.commit()
    except Exception:
        pass
    finally:
        con.close()


def gerar_um(cand: dict, day: str, db_path: Path = DB_PATH,
             factory_data: Path = FACTORY_DATA, sim: bool = False,
             exemplo: str = "", uploader=None) -> dict:
    lid = longo_id(cand["clip_id"])
    if _por_clip(db_path, cand["clip_id"]):
        return {"ok": False, "skip": "já existe"}
    dur_vod = _vod_duracao(cand["vod_url"])
    w = janela(cand["vod_offset"], cand["duracao"], dur_vod)
    if not w:
        return {"ok": False, "skip": "VOD sem 10 min em volta"}
    start, end, dur = w
    out_dir = factory_data / day / "longos"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = out_dir / f"src-{lid}.mp4"
    if not baixar_trecho(cand["vod_url"], start, end, src):
        return {"ok": False, "skip": "download falhou"}
    real = _duracao_mp4(src)
    if real < LONGO_ALVO - 2:
        return {"ok": False, "skip": f"trecho curto ({real:.0f}s)"}
    final = out_dir / f"longo-{lid}.mp4"
    if not render_longo(src, final, duracao=LONGO_ALVO):
        return {"ok": False, "skip": "render falhou"}
    row = {
        "longo_id": lid, "dia": day, "streamer": cand["streamer"],
        "origem": "clip", "clip_id": cand["clip_id"],
        "titulo_clip": cand["titulo_clip"],
        "video_id": cand["vod_id"], "vod_url": cand["vod_url"],
        "t_inicio": start, "duracao": dur, "jogo": cand["jogo"],
        "titulo": _titulo(cand), "descricao": _descricao(cand),
        "caption": _descricao(cand), "video_url": "",
        "preview_file_id": "", "preview_msg_id": 0,
        "thumb_base": None, "thumb_texto": "", "thumb_url": "",
        "thumb_msg_id": 0, "status": "gerado", "due_at": "",
        "buffer_id": "", "criado_em": _now().isoformat(),
    }
    base = _render_base(row, src, cand["vod_offset"] - start, out_dir)
    if not base:
        return {"ok": False, "skip": "thumb base falhou"}
    base_jpg, _box = base
    row["thumb_base"] = base_jpg.read_bytes()
    if not sim:
        up = (uploader or upload_public.upload)(final)
        if not up:
            return {"ok": False, "skip": "upload do vídeo falhou"}
        row["video_url"] = up
    preview = out_dir / f"preview-{lid}.mp4"
    if not gerar_preview(final, preview):
        return {"ok": False, "skip": "preview falhou"}
    _salvar(db_path, row)
    res = enviar_previews(row, base_jpg, preview, exemplo=exemplo if sim else "",
                          db_path=db_path)
    if not res.get("ok"):
        _update(db_path, lid, status="gerado")
        return {"ok": False, "skip": res.get("error", "telegram falhou")}
    _registrar_clip_visto(db_path, cand)
    if not sim:
        for p in (src, final, preview):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
    return {"ok": True, "longo_id": lid, "titulo": row["titulo"],
            "video_url": row["video_url"]}


def aplicar_texto(lid: str, texto: str, db_path: Path = DB_PATH,
                  botoes: bool = True) -> dict:
    row = _row(db_path, lid)
    if not row:
        return {"ok": False, "error": f"longo {lid} desconhecido"}
    if row.get("status") in ("agendado", "aprovado"):
        return {"ok": False, "error": "já aprovado/agendado"}
    if row.get("status") == "rejeitado":
        return {"ok": False, "error": "longo descartado"}
    parts = parse_texto(texto)
    campos = {}
    if "thumb" in parts:
        campos["thumb_texto"] = parts["thumb"]
    if "titulo" in parts and parts["titulo"]:
        campos["titulo"] = parts["titulo"][:95]
    if "desc" in parts and parts["desc"]:
        campos["descricao"] = parts["desc"][:2000]
        campos["caption"] = parts["desc"][:2000]
    if not campos:
        return {"ok": False, "error": "nada para atualizar"}
    merged = {**row, **campos}
    blob = row.get("thumb_base")
    if not blob:
        return {"ok": False, "error": "thumb base sumiu"}
    with tempfile.TemporaryDirectory(prefix="longo-thumb-") as tmp:
        base = Path(tmp) / "base.jpg"
        base.write_bytes(bytes(blob))
        out = Path(tmp) / "final.jpg"
        max_w = 1100 if LONGO_THUMB_ESTILO == "clean" else 820
        if not render_thumb_texto(base, str(merged.get("thumb_texto") or ""),
                                  out, max_w=max_w):
            return {"ok": False, "error": "render da thumb falhou"}
        url = _upload_imagem(out)
        if not url:
            return {"ok": False, "error": "upload da thumb falhou"}
        _update(db_path, lid, thumb_url=url, status="texto", **campos)
        token, chat = _tg()
        if token and chat:
            api = f"https://api.telegram.org/bot{token}"
            cap = (
                "🖼️ THUMB FINAL — ✅ aprova e agenda | ❌ descarta\n"
                f"📌 {str(merged.get('titulo') or '')[:90]}\n"
                f"📝 {str(merged.get('descricao') or '')[:420]}\n"
                f"🆔 {lid}")
            kb = ({"inline_keyboard": [[
                {"text": "✅ Aprovar", "callback_data": f"lth:{lid}"},
                {"text": "❌ Descartar", "callback_data": f"ltr:{lid}"}]]}
                if botoes else None)
            try:
                _send_photo(api, chat, out, cap, kb)
            except Exception as exc:
                return {"ok": False, "error": f"telegram: {type(exc).__name__}"}
    return {"ok": True, "longo_id": lid, "thumb_url": url,
            "titulo": merged.get("titulo"), "thumb_texto": merged.get("thumb_texto")}


def finalizar_sem_texto(lid: str, db_path: Path = DB_PATH) -> dict:
    return aplicar_texto(lid, "thumb: ", db_path=db_path)


def aprovar(lid: str, db_path: Path = DB_PATH) -> dict:
    row = _row(db_path, lid)
    if not row:
        return {"ok": False, "error": f"longo {lid} desconhecido"}
    if row.get("status") in ("agendado", "aprovado"):
        return {"ok": False, "error": f"já agendado: {due_brt(str(row.get('due_at')))}"}
    if row.get("status") == "rejeitado":
        return {"ok": False, "error": "longo descartado"}
    if not row.get("video_url"):
        return {"ok": False, "error": "vídeo sem URL pública (simulação?)"}
    token = os.environ.get("BUFFER_API_KEY", "")
    if not token:
        return {"ok": False, "error": "sem BUFFER_API_KEY"}
    try:
        chans = _buf.channels(token)
    except Exception as exc:
        return {"ok": False, "error": f"Buffer: {type(exc).__name__}"}
    ch = chans.get("youtube", "")
    if not ch:
        return {"ok": False, "error": "YouTube não conectado no Buffer"}
    due = proximo_slot_longo(db_path)
    if not due:
        return {"ok": False, "error": "sem slot livre"}
    try:
        pid = _buf.create_post(
            token, "youtube", ch, str(row.get("caption") or row.get("descricao") or "")[:2100],
            str(row["video_url"]), due, str(row.get("titulo") or "ViraClipe")[:95],
            thumbnail_url=str(row.get("thumb_url") or ""), category_id="20")
    except Exception as exc:
        return {"ok": False, "error": f"Buffer: {str(exc)[:160]}"}
    _update(db_path, lid, status="agendado", due_at=due, buffer_id=pid)
    return {"ok": True, "longo_id": lid, "due_at": due,
            "due_brt": due_brt(due), "post_id": pid}


def rejeitar(lid: str, db_path: Path = DB_PATH) -> dict:
    row = _row(db_path, lid)
    if not row:
        return {"ok": False, "error": f"longo {lid} desconhecido"}
    if row.get("status") == "agendado":
        return {"ok": False, "error": "já agendado no Buffer"}
    _update(db_path, lid, status="rejeitado")
    return {"ok": True, "longo_id": lid}


def _clip_candidato(streamer: str, clip_id: str) -> dict | None:
    tw_id = os.environ.get("TWITCH_CLIENT_ID", "")
    tw_sec = os.environ.get("TWITCH_CLIENT_SECRET", "")
    try:
        clips = _clips.fetch_clips(streamer, tw_id, tw_sec, days=14, first=100)
    except Exception:
        return None
    for c in clips:
        if str(c.get("clip_id")) == clip_id:
            return _candidato(c)
    return None


def main(argv: list[str] | None = None) -> int:
    _load_env()
    ap = argparse.ArgumentParser(description="longos 10+ min (YouTube)")
    ap.add_argument("--date", default=_today())
    ap.add_argument("--max", type=int, default=LONGO_MAX_DIA)
    ap.add_argument("--sim", action="store_true", help="só prévia no Telegram")
    ap.add_argument("--streamer", default="")
    ap.add_argument("--clip", default="")
    ap.add_argument("--exemplo", default="")
    ap.add_argument("--texto", default="", help="aplica texto num longo já gerado")
    ap.add_argument("--longo", default="", help="id do longo p/ --texto")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--factory", default=str(FACTORY_DATA))
    args = ap.parse_args(argv)
    if args.max <= 0:
        print("longos: pausado (--max 0)")
        return 0
    db_path = Path(args.db)
    factory_data = Path(args.factory)
    _db.init_db(db_path)

    if args.texto:
        lid = args.longo
        if not lid and args.clip:
            lid = longo_id(args.clip)
        if not lid:
            con = _db.connect(db_path)
            try:
                r = con.execute("SELECT longo_id FROM longos"
                                " ORDER BY criado_em DESC LIMIT 1").fetchone()
                lid = str(r[0]) if r else ""
            finally:
                con.close()
        if not lid:
            print("longos: nenhum longo no banco")
            return 1
        res = aplicar_texto(lid, args.texto, db_path=db_path,
                            botoes=not args.sim)
        print("longos:", json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    cands: list[dict] = []
    if args.clip:
        c = _clip_candidato(args.streamer, args.clip)
        if c:
            cands = [c]
    if not cands:
        cands = selecionar_candidatos(args.date, db_path, max_n=max(1, args.max))
    if not cands:
        print("longos: sem clipe novo com VOD (nada a fazer)")
        return 1
    feitos, erros = [], []
    for c in cands:
        if len(feitos) >= max(1, args.max):
            break
        try:
            res = gerar_um(c, args.date, db_path=db_path,
                           factory_data=factory_data, sim=args.sim,
                           exemplo=args.exemplo)
        except Exception as exc:
            res = {"ok": False, "skip": f"{type(exc).__name__}: {exc}"}
        if res.get("ok"):
            feitos.append(res)
            print(f"longos: OK {res['longo_id']} {res['titulo'][:60]}")
        else:
            erros.append(f"{c.get('clip_id')}: {res.get('skip')}")
            print(f"longos: skip {c.get('clip_id')} -> {res.get('skip')}")
    print(f"longos: {len(feitos)} gerado(s), {len(erros)} pulado(s)")
    return 0 if feitos else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
