"""Signals locais custo zero: chat + áudio -> candidatos.json.

Zero calls de API. Tudo roda no Termux (ffmpeg + JSON).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

WINDOW = 30.0
MIN_DUR = 25.0
MAX_DUR = 70.0
TOP_N = 30

EBUR_RE = re.compile(r"t:\s*([\d.]+).*?M:\s*(-?[\d.]+)")


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [50.0] * len(values)
    return [100.0 * (v - lo) / (hi - lo) for v in values]


def chat_windows(messages: list[dict], window: float = WINDOW) -> list[dict]:
    """Bucketiza chat em janelas de `window`s; score = percentil de densidade."""
    if not messages:
        return []
    tmax = max(float(m.get("t") or 0) for m in messages)
    n = max(1, int(tmax // window) + 1)
    counts = [0.0] * n
    for m in messages:
        i = min(n - 1, max(0, int(float(m.get("t") or 0) // window)))
        counts[i] += 1.0 + 0.5 * float(m.get("emotes") or 0)
    scores = _normalize(counts)
    return [
        {"t_inicio": i * window, "t_fim": (i + 1) * window, "chat": round(s, 1)}
        for i, s in enumerate(scores)
    ]


def parse_ebur128(stderr_text: str) -> list[tuple[float, float]]:
    """Extrai (t, M) do stderr do ffmpeg ebur128."""
    out = []
    for m in EBUR_RE.finditer(stderr_text or ""):
        try:
            out.append((float(m.group(1)), float(m.group(2))))
        except ValueError:
            continue
    return out


def ebur128_peaks(mp4: Path, runner=subprocess.run) -> list[tuple[float, float]]:
    try:
        r = runner(
            ["ffmpeg", "-hide_banner", "-i", str(mp4),
             "-af", "ebur128", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600,
        )
        return parse_ebur128((r.stderr or "") + "\n" + (r.stdout or ""))
    except Exception:
        return []


def audio_windows(peaks: list[tuple[float, float]], window: float = WINDOW) -> list[dict]:
    if not peaks:
        return []
    tmax = max(t for t, _ in peaks)
    n = max(1, int(tmax // window) + 1)
    # picos são negativos (dB); converte para energia positiva
    best = [float("-inf")] * n
    for t, m in peaks:
        i = min(n - 1, max(0, int(t // window)))
        best[i] = max(best[i], m)
    vals = [b if b != float("-inf") else -70.0 for b in best]
    scores = _normalize(vals)
    return [
        {"t_inicio": i * window, "t_fim": (i + 1) * window, "audio": round(s, 1)}
        for i, s in enumerate(scores)
    ]


def fuse(
    cw: list[dict], aw: list[dict], top_n: int = TOP_N,
    min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
) -> list[dict]:
    """Junta chat+áudio por janela, expande p/ min_dur e ordena.

    Pesos via SIGNAL_W_CHAT/AUDIO (default público 0.7/0.3).
    """
    from config.secret_loader import signal_weights

    w_chat, w_audio = signal_weights()
    audio_by_i = {int(w["t_inicio"] // WINDOW): w["audio"] for w in aw}
    cands = []
    for w in cw:
        i = int(w["t_inicio"] // WINDOW)
        a = float(audio_by_i.get(i, 50.0))
        c = float(w["chat"])
        combinado = round(w_chat * c + w_audio * a, 1)
        ini = float(w["t_inicio"])
        fim = float(w["t_fim"])
        if fim - ini < min_dur:
            mid = (ini + fim) / 2
            ini = max(0.0, mid - min_dur / 2)
            fim = ini + min_dur
        if fim - ini > max_dur:
            fim = ini + max_dur
        cands.append({
            "t_inicio": round(ini, 1), "t_fim": round(fim, 1),
            "duracao": round(fim - ini, 1),
            "chat": c, "audio": round(a, 1), "combinado": combinado,
        })
    # remove sobreposição forte: mantém maior combinado
    cands.sort(key=lambda c: c["combinado"], reverse=True)
    escolhidos: list[dict] = []
    for c in cands:
        if all(abs(c["t_inicio"] - e["t_inicio"]) > (MIN_DUR / 2) for e in escolhidos):
            escolhidos.append(c)
        if len(escolhidos) >= top_n:
            break
    return escolhidos


def build_candidatos(day_dir: Path, ingest_item: dict, runner=subprocess.run) -> list[dict]:
    try:
        messages = json.loads(Path(ingest_item["chat"]).read_text(encoding="utf-8"))
    except Exception:
        messages = []
    cw = chat_windows(messages if isinstance(messages, list) else [])
    mp4 = Path(ingest_item.get("mp4", ""))
    peaks = ebur128_peaks(mp4, runner=runner) if mp4.exists() else []
    print(f"signals: {ingest_item.get('video_id')} "
          f"chat_msgs={len(messages) if isinstance(messages, list) else '?!'} "
          f"mp4={'ok' if mp4.exists() else 'AUSENTE'} picos={len(peaks)}")
    aw = audio_windows(peaks)
    if not cw and not aw:
        return []
    if not cw:
        cw = [{"t_inicio": w["t_inicio"], "t_fim": w["t_fim"], "chat": 50.0} for w in aw]
    cands = fuse(cw, aw)
    for c in cands:
        c["video_id"] = ingest_item.get("video_id")
        c["streamer"] = ingest_item.get("streamer")
        c["plataforma"] = ingest_item.get("plataforma")
        c["url"] = ingest_item.get("url")
    return cands


def signals_day(day: str, factory_data: Path, runner=subprocess.run) -> list[dict]:
    day_dir = factory_data / day
    ing_path = day_dir / "ingest.json"
    if not ing_path.exists():
        return []
    ingest = json.loads(ing_path.read_text(encoding="utf-8"))
    todos: list[dict] = []
    for item in ingest:
        todos.extend(build_candidatos(day_dir, item, runner=runner))
    todos.sort(key=lambda c: c["combinado"], reverse=True)
    todos = todos[:TOP_N]
    (day_dir / "candidatos.json").write_text(
        json.dumps(todos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return todos
