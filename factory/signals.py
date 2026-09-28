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
SIL_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
SIL_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [50.0] * len(values)
    return [100.0 * (v - lo) / (hi - lo) for v in values]


# Palavras que indicam reação forte do chat (hype/riso/choque).
_HYPE_RE = re.compile(
    r"(pog|poggers|pogu|gg+\b|wp+|clutch|insano|insane|que isso|what|wtf|lol+|"
    r"k{3,}|hahaha+|kkk+|rsrs+|clip|clipa|lenda|mito|goat|ez\b|amassou|"
    r"\+1|f\b|rip\b|omegalul|lul+|kekw|monkas|pogchamp|ezclap|gachi|"
    r"surreal|absurdo|crazy|no way|let'?s go+|vamoo+|boraa+)",
    re.IGNORECASE,
)


def chat_windows(messages: list[dict], window: float = WINDOW) -> list[dict]:
    """Bucketiza chat em janelas; score = densidade ponderada (0-100).

    Pondera: volume + usuários únicos + emotes + CAPS + keywords de hype.
    Spike de gente diferente reagindo vale mais que 1 spammer.
    """
    if not messages:
        return []
    tmax = max(float(m.get("t") or 0) for m in messages)
    n = max(1, int(tmax // window) + 1)
    counts = [0.0] * n
    uniques: list[set] = [set() for _ in range(n)]
    for m in messages:
        i = min(n - 1, max(0, int(float(m.get("t") or 0) // window)))
        msg = str(m.get("msg") or "")
        emotes = float(m.get("emotes") or 0)
        author = str(m.get("author") or m.get("user") or "")
        uniques[i].add(author or f"anon-{i}")
        hype = 1.0 if _HYPE_RE.search(msg) else 0.0
        caps = sum(1 for c in msg if c.isupper())
        caps_bonus = min(1.0, caps / 15.0) if len(msg) > 8 else 0.0
        counts[i] += 1.0 + 0.5 * emotes + 1.5 * hype + 0.5 * caps_bonus
    # bônus de diversidade: janela com muita gente diferente sobe
    if uniques:
        umax = max(len(u) for u in uniques) or 1
        for i in range(n):
            counts[i] += 2.0 * (len(uniques[i]) / umax)
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


def ebur_cmd(mp4: Path) -> list[str]:
    # -vn/-sn/-dn: só áudio (sem isso, VODs de horas decodificam vídeo à toa).
    return ["ffmpeg", "-hide_banner", "-i", str(mp4),
            "-vn", "-sn", "-dn", "-af", "ebur128", "-f", "null", "-"]


def ebur128_peaks(mp4: Path, runner=subprocess.run) -> list[tuple[float, float]]:
    try:
        r = runner(ebur_cmd(mp4), capture_output=True, text=True, timeout=900)
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


def silence_cmd(mp4: Path) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-i", str(mp4),
            "-vn", "-sn", "-dn", "-af", "silencedetect=noise=-30dB:d=0.5",
            "-f", "null", "-"]


def silence_intervals(mp4: Path, runner=subprocess.run) -> list[tuple[float, float]]:
    """Intervalos de silêncio [(ini, fim)] — proxy de 'sem fala' (local, free)."""
    try:
        r = runner(silence_cmd(mp4), capture_output=True, text=True, timeout=900)
        blob = (r.stderr or "") + "\n" + (r.stdout or "")
    except Exception:
        return []
    starts = [float(m.group(1)) for m in SIL_START_RE.finditer(blob)]
    ends = [float(m.group(1)) for m in SIL_END_RE.finditer(blob)]
    return list(zip(starts, ends)) if len(starts) == len(ends) else []


def speech_density(silences: list[tuple[float, float]], t0: float, t1: float) -> float:
    """Fração da janela COM som/fala (0-1). Sem dados: 1.0 (não pune)."""
    if t1 <= t0:
        return 1.0
    quiet = sum(max(0.0, min(e, t1) - max(s, t0)) for s, e in silences)
    return max(0.0, min(1.0, 1.0 - quiet / (t1 - t0)))


def speech_windows(mp4: Path, silences: list[tuple[float, float]],
                   window: float = WINDOW) -> dict[int, float]:
    """Densidade de fala por janela (índice -> 0-100)."""
    if not mp4.exists():
        return {}
    try:
        from .qc import ffprobe as _probe
        dur = float((_probe(mp4).get("format") or {}).get("duration") or 0)
    except Exception:
        dur = 0.0
    if dur <= 0:
        return {}
    n = max(1, int(dur // window) + 1)
    return {i: round(100.0 * speech_density(silences, i * window, (i + 1) * window), 1)
            for i in range(n)}


def adaptive_bounds(ini: float, fim: float, silences: list[tuple[float, float]],
                    min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
                    max_back: float = 15.0) -> tuple[float, float]:
    """Expande p/ trás até o início da fala contínua (pega o setup) e trima
    silêncio do fim. Para em silêncio >=3s; respeita min/max_dur."""
    start = ini
    back = 0.0
    while back < max_back and start > 0:
        probe = (max(0.0, start - 2.0), start)
        gap = sum(max(0.0, min(e, probe[1]) - max(s, probe[0])) for s, e in silences)
        if gap >= 1.5:  # trecho majoritariamente silencioso: aqui começa
            break
        start = probe[0]
        back += 2.0
    end = fim
    while end - start > min_dur:
        probe = (end - 2.0, end)
        gap = sum(max(0.0, min(e, probe[1]) - max(s, probe[0])) for s, e in silences)
        if gap < 1.5:  # tem fala no fim: mantém
            break
        end = probe[0]
    if end - start < min_dur:
        end = start + min_dur
    if end - start > max_dur:
        end = start + max_dur
    return round(max(0.0, start), 1), round(end, 1)


def fuse(
    cw: list[dict], aw: list[dict], top_n: int = TOP_N,
    min_dur: float = MIN_DUR, max_dur: float = MAX_DUR,
    speech: dict[int, float] | None = None,
    silences: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Junta chat+áudio por janela, expande p/ min_dur e ordena.

    Pesos via SIGNAL_W_CHAT/AUDIO (default público 0.7/0.3).
    Gate de voz: pico sem fala densa perde até 75% (some som de jogo vazio).
    Janela adaptativa: inclui setup (fala contínua p/ trás), trima gordura.
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
        voz = float((speech or {}).get(i, 100.0))
        if speech:
            combinado = round(combinado * (0.25 + 0.75 * voz / 100.0), 1)
        ini = float(w["t_inicio"])
        fim = float(w["t_fim"])
        if fim - ini < min_dur:
            mid = (ini + fim) / 2
            ini = max(0.0, mid - min_dur / 2)
            fim = ini + min_dur
        if silences is not None:
            ini, fim = adaptive_bounds(ini, fim, silences, min_dur, max_dur)
        elif fim - ini > max_dur:
            fim = ini + max_dur
        cands.append({
            "t_inicio": round(ini, 1), "t_fim": round(fim, 1),
            "duracao": round(fim - ini, 1),
            "chat": c, "audio": round(a, 1), "voz": round(voz, 1),
            "combinado": combinado,
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
    sil = silence_intervals(mp4, runner=runner) if mp4.exists() else []
    sp = speech_windows(mp4, sil) if mp4.exists() else {}
    print(f"signals: {ingest_item.get('video_id')} "
          f"chat_msgs={len(messages) if isinstance(messages, list) else '?!'} "
          f"mp4={'ok' if mp4.exists() else 'AUSENTE'} picos={len(peaks)} "
          f"silencios={len(sil)}")
    aw = audio_windows(peaks)
    if not cw and not aw:
        return []
    has_chat = bool(cw)
    if not cw:
        cw = [{"t_inicio": w["t_inicio"], "t_fim": w["t_fim"], "chat": 50.0} for w in aw]
    cands = fuse(cw, aw, speech=sp or None, silences=sil or None)
    for c in cands:
        c["video_id"] = ingest_item.get("video_id")
        c["streamer"] = ingest_item.get("streamer")
        c["plataforma"] = ingest_item.get("plataforma")
        c["url"] = ingest_item.get("url")
        if not has_chat:
            c["chat"] = None  # sem replay: score renormaliza (audio+llm)
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
