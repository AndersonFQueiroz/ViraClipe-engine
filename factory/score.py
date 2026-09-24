"""Score 2º estágio: 1 call Gemini Flash por candidato + fallback local.

score_final = 0.5*chat + 0.2*audio + 0.3*viral_score
Publica se >= SCORE_THRESHOLD. Sem GEMINI_API_KEY ou em 429/quota,
usa fallback local (viral=None, título template) sem travar o dia.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from config.secret_loader import get_gemini_prompt, score_weights

# Prompt público capado — full vem via VIRACLIP_PROMPT[_B64] em runtime.
PROMPT = (
    "Você avalia um trecho de live para cortes virais em PT-BR. "
    "Retorne SOMENTE JSON: "
    '{"viral_score":0-100,"motivo":"","titulo":"","descricao":"","hashtags":[]}. '
    "viral_score alto = reação forte, frase de efeito, gameplay insano, humor. "
    "titulo curto <70 chars sem clickbait mentiroso. descricao 1-2 frases + crédito ao streamer. "
    "hashtags max 5 sem #."
)

JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def active_prompt() -> str:
    return get_gemini_prompt()


def score_final(chat: float | None, audio: float, viral: float | None) -> float:
    v = float(viral) if viral is not None else 50.0
    w_chat, w_audio, w_llm = score_weights()
    if chat is None:
        # Sem replay de chat (ex: Twitch via lib quebrada): redistribui o peso
        # do chat proporcionalmente entre áudio e LLM. Registrado em 'renorm'.
        tot = (w_audio + w_llm) or 1.0
        return round((w_audio / tot) * float(audio) + (w_llm / tot) * v, 1)
    return round(w_chat * float(chat) + w_audio * float(audio) + w_llm * v, 1)


def fallback_title(streamer: str) -> str:
    return f"Melhor momento de @{streamer}"[:70]


def parse_gemini_json(text: str) -> dict:
    m = JSON_RE.search(text or "")
    if not m:
        raise ValueError("resposta sem JSON")
    data = json.loads(m.group(0))
    viral = float(data.get("viral_score", 50))
    data["viral_score"] = max(0.0, min(100.0, viral))
    data.setdefault("motivo", "")
    data.setdefault("titulo", "")
    data.setdefault("descricao", "")
    tags = data.get("hashtags") or []
    data["hashtags"] = [str(t).lstrip("#")[:30] for t in tags][:5]
    return data


def call_gemini(transcrito: str, streamer: str, model: str, api_key: str, timeout: int = 60) -> dict:
    """1 call Flash. Import tardio para não quebrar no Termux sem a lib."""
    from google import genai  # type: ignore
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=f"{active_prompt()}\nSTREAMER: {streamer}\nTRECHO: {transcrito[:4000]}",
    )
    text = getattr(resp, "text", "") or ""
    return parse_gemini_json(text)


def score_candidatos(
    candidatos: list[dict],
    transcritos: dict[str, str] | None = None,
    model: str = "gemini-3.6-flash",
    api_key: str = "",
    threshold: float = 75.0,
    daily_cap: int = 5,
    gemini_fn=None,
    audit_path: Path | None = None,
) -> list[dict]:
    transcritos = transcritos or {}
    fn = gemini_fn or (call_gemini if api_key else None)
    scored: list[dict] = []
    for i, c in enumerate(candidatos):
        key = f"{c.get('video_id')}:{c.get('t_inicio')}"
        texto = transcritos.get(key, "")
        viral = None
        streamer = str(c.get("streamer") or "")
        titulo = fallback_title(streamer)
        # Crédito garantido mesmo em degradado (QC exige @ ou link na legenda)
        fb_cred = f"Créditos: @{streamer}" + (f" — {c.get('url')}" if c.get("url") else "")
        descricao, hashtags, motivo = fb_cred, [], ""
        if fn is not None:
            try:
                data = fn(texto, str(c.get("streamer") or ""), model, api_key) if gemini_fn is None else fn(texto, c)
                viral = float(data.get("viral_score", 50))
                titulo = str(data.get("titulo") or titulo)[:70]
                descricao = str(data.get("descricao") or "")
                hashtags = list(data.get("hashtags") or [])
                motivo = str(data.get("motivo") or "")
                # Normaliza crédito (QC bloqueia sem @streamer ou link na legenda)
                _txt = f"{titulo} {descricao}"
                if streamer and "@" not in _txt and "twitch.tv" not in _txt and "youtube.com" not in _txt:
                    descricao = (descricao + f" Créditos: @{streamer}").strip()
            except Exception:
                viral = None
        chat = c.get("chat", 50)
        chat_f = None if chat is None else float(chat)
        final = score_final(chat_f, float(c.get("audio", 50)), viral)
        scored.append({
            **c, "cut_id": f"{c.get('video_id')}-{float(c.get('t_inicio', 0)):.0f}",
            "viral": viral, "score_final": final, "titulo": titulo,
            "descricao": descricao, "hashtags": hashtags, "motivo": motivo,
            "renorm": chat is None,
        })
    scored.sort(key=lambda s: s["score_final"], reverse=True)
    if audit_path is not None:
        try:
            audit_path.write_text(json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
    return [s for s in scored if s["score_final"] >= threshold][:daily_cap]


def score_day(
    day: str, factory_data: Path, model: str = "gemini-3.6-flash",
    api_key: str = "", threshold: float = 75.0, daily_cap: int = 5,
    gemini_fn=None, transcritos: dict[str, str] | None = None,
) -> list[dict]:
    day_dir = factory_data / day
    cand_path = day_dir / "candidatos.json"
    if not cand_path.exists():
        return []
    cands = json.loads(cand_path.read_text(encoding="utf-8"))
    out = score_candidatos(cands, transcritos, model, api_key, threshold, daily_cap, gemini_fn,
                           audit_path=day_dir / "scored_full.json")
    (day_dir / "scored.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out
