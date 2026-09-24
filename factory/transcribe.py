"""Transcrição dos snippets candidatos via Gemini áudio (1 call por trecho).

Fecha o gap do score cego: score_day recebia transcritos={} e o Gemini
avaliava TRECHO vazio. Extrai mp3 leve do snippet (ffmpeg) e transcreve.
Sem GEMINI_API_KEY ou em falha → {} (fallback local assume, sem travar).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

PROMPT_TRANSCRIBE = (
    "Transcreva o áudio literalmente em PT-BR, só o texto falado, "
    "sem comentários nem formatação. Se não houver fala, retorne OUVIDO_VAZIO."
)

MAX_SNIPPETS = 6


def extract_snippet_audio(mp4: Path, t_inicio: float, duracao: float,
                          out_mp3: Path, runner=subprocess.run) -> bool:
    try:
        r = runner(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{t_inicio:.1f}", "-t", f"{min(float(duracao), 70.0):.1f}",
             "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "libmp3lame", "-b:a", "32k", str(out_mp3)],
            capture_output=True, text=True, timeout=300,
        )
        return r.returncode == 0 and out_mp3.exists() and out_mp3.stat().st_size > 1_000
    except Exception:
        return False


def transcribe_file(mp3: Path, model: str, api_key: str, timeout: int = 120) -> str:
    """Sobe o mp3 ao Files API, transcreve, apaga remoto. 1 retry em 429/503."""
    from google import genai  # type: ignore

    from . import net as _net

    def _do(key: str) -> str:
        client = genai.Client(api_key=key or api_key)
        remote = client.files.upload(file=str(mp3))
        try:
            deadline = time.time() + timeout
            while getattr(remote, "state", None) not in (None, "ACTIVE"):
                if time.time() > deadline:
                    raise TimeoutError("arquivo não ativou no Files API")
                time.sleep(2)
                remote = client.files.get(name=remote.name)
            resp = client.models.generate_content(
                model=model, contents=[PROMPT_TRANSCRIBE, remote],
            )
            return (getattr(resp, "text", "") or "").strip()[:4000]
        finally:
            try:
                client.files.delete(name=remote.name)
            except Exception:
                pass

    return _net.llm_with_keys(_do, api_key)


def transcribe_day(day: str, factory_data: Path, model: str = "gemini-3.6-flash",
                   api_key: str = "", max_snippets: int = MAX_SNIPPETS,
                   runner=subprocess.run, transcriber=None) -> dict[str, str]:
    """Transcreve top candidatos; salva day/transcritos.json. Retorna mapa."""
    day_dir = factory_data / day
    cand_path = day_dir / "candidatos.json"
    if not cand_path.exists() or not api_key:
        return {}
    cands = json.loads(cand_path.read_text(encoding="utf-8"))[:max(0, max_snippets)]
    ing_path = day_dir / "ingest.json"
    mp4_by_vid = {}
    if ing_path.exists():
        for v in json.loads(ing_path.read_text(encoding="utf-8")):
            mp4_by_vid[str(v.get("video_id"))] = str(v.get("mp4") or "")
    out: dict[str, str] = {}
    cache_path = day_dir / "transcritos.json"
    if cache_path.exists():
        try:
            out.update(json.loads(cache_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    fn = transcriber or (lambda mp3: transcribe_file(mp3, model, api_key))
    audio_dir = day_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    import os as _os

    try:
        pace = float(_os.environ.get("LLM_PACE_SEC", "4"))
    except ValueError:
        pace = 4.0
    first = True
    err_logged = False
    for c in cands:
        key = f"{c.get('video_id')}:{c.get('t_inicio')}"
        if out.get(key):
            continue
        src = mp4_by_vid.get(str(c.get("video_id")), "")
        if not src or not Path(src).exists():
            continue
        dur = float(c.get("duracao") or (float(c.get("t_fim", 30)) - float(c.get("t_inicio", 0))))
        mp3 = audio_dir / f"{c.get('video_id')}-{float(c.get('t_inicio', 0)):.0f}.mp3"
        if not (mp3.exists() and mp3.stat().st_size > 1_000):
            if not extract_snippet_audio(Path(src), float(c.get("t_inicio", 0)), dur, mp3, runner=runner):
                continue
        try:
            if not first and transcriber is None and pace > 0:
                time.sleep(pace)
            first = False
            out[key] = fn(mp3)
        except Exception as exc:
            if not err_logged:
                print(f"transcribe: falhou ({type(exc).__name__}: {str(exc)[:120]})")
                err_logged = True
            continue
    cache_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
