"""Split público/privado do ViraClipe.

Modo público (fork): roda com defaults capados, sem segredo.
Modo full (dono): injeta tempero via env / GH Secrets, sem commitar.

NUNCA logar valores aqui — só booleanos/contagens.
"""
from __future__ import annotations

import base64
import json
import os


def _raw(name: str) -> str:
    return os.environ.get(name, "")


def get_secret(name: str, default: str = "") -> str:
    """Lê env direto ou variante _B64 (base64). Nunca logar o retorno."""
    b64 = os.environ.get(f"{name}_B64", "")
    if b64.strip():
        try:
            return base64.b64decode(b64.strip()).decode("utf-8", "replace")
        except Exception:
            pass
    val = os.environ.get(name, "")
    return val if val else default


def is_full_mode() -> bool:
    """True se tempero privado presente (qualquer um destes)."""
    markers = (
        "VIRACLIP_PROMPT",
        "VIRACLIP_PROMPT_B64",
        "VIRACLIP_BLOCKLIST",
        "VIRACLIP_BLOCKLIST_B64",
        "VIRACLIP_PACK_JSON",
        "VIRACLIP_PACK_JSON_B64",
    )
    return any(os.environ.get(m, "").strip() for m in markers)


def mode_label() -> str:
    return "full" if is_full_mode() else "publico-capado"


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


# Pesos afináveis — fork usa default mediano, dono afina via env.
def score_weights() -> tuple[float, float, float]:
    return (
        env_float("SCORE_W_CHAT", 0.5),
        env_float("SCORE_W_AUDIO", 0.2),
        env_float("SCORE_W_LLM", 0.3),
    )


def signal_weights() -> tuple[float, float]:
    return (
        env_float("SIGNAL_W_CHAT", 0.7),
        env_float("SIGNAL_W_AUDIO", 0.3),
    )


PUBLIC_PROMPT = (
    "Você avalia um trecho de live para cortes virais em PT-BR. "
    "Retorne SOMENTE JSON: "
    '{"viral_score":0-100,"motivo":"","titulo":"","descricao":"","hashtags":[]}. '
    "viral_score alto = reação forte, frase de efeito, gameplay insano, humor. "
    "titulo curto <70 chars sem clickbait mentiroso. descricao 1-2 frases + crédito ao streamer. "
    "hashtags max 5 sem #."
)


def get_gemini_prompt() -> str:
    """Prompt full via VIRACLIP_PROMPT[_B64], senão público capado."""
    return get_secret("VIRACLIP_PROMPT", PUBLIC_PROMPT)


PUBLIC_TAGS = ["cortes", "clipes", "livetwitch", "melhoresmomentos", "viral"]
PUBLIC_CTA = {
    "youtube": "Link da live original na descrição 👆",
    "instagram": "Live completa no link da VOD 👇",
    "tiktok": "Segue pra mais 👇",
    "kwai": "Segue pra mais cortes 👇",
}
PUBLIC_HANDLE = "@ViraClipe"


def get_tags_base() -> list[str]:
    raw = get_secret("VIRACLIP_TAGS", "")
    if raw.strip():
        tags = [t.strip().lstrip("#")[:30] for t in raw.replace(",", " ").split() if t.strip()]
        if tags:
            return tags[:8]
    # JSON privado também pode trazer tags
    pack = get_pack_override()
    if isinstance(pack.get("tags_base"), list) and pack["tags_base"]:
        return [str(t).lstrip("#")[:30] for t in pack["tags_base"]][:8]
    return list(PUBLIC_TAGS)


def get_cta() -> dict:
    pack = get_pack_override()
    cta = dict(PUBLIC_CTA)
    if isinstance(pack.get("cta"), dict):
        for k, v in pack["cta"].items():
            if isinstance(v, str) and v.strip():
                cta[str(k)] = v.strip()[:120]
        return cta
    for net in ("youtube", "instagram", "tiktok", "kwai"):
        v = os.environ.get(f"VIRACLIP_CTA_{net.upper()}", "").strip()
        if v:
            cta[net] = v[:120]
    return cta


def get_handle() -> str:
    pack = get_pack_override()
    h = str(pack.get("handle") or "").strip()
    if h:
        return h[:30]
    return os.environ.get("VIRACLIP_HANDLE", PUBLIC_HANDLE).strip()[:30] or PUBLIC_HANDLE


def get_pack_override() -> dict:
    raw = get_secret("VIRACLIP_PACK_JSON", "")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_blocklist_extra() -> list[str]:
    """Termos privados (vírgula ou linha) — somados à blocklist pública."""
    raw = get_secret("VIRACLIP_BLOCKLIST", "")
    if not raw.strip():
        return []
    parts = raw.replace(",", "\n").splitlines()
    out = []
    for p in parts:
        t = p.strip().lower()[:60]
        if t and not t.startswith("#"):
            out.append(t)
    return out[:200]
