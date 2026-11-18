"""Config central do ViraClipe (Fase 1 pós-live, tudo free)."""
from __future__ import annotations

import datetime as _dt
import os
import re as _re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def env_list(name: str) -> list[str]:
    """Envs em lista separada por vírgula (espaços tolerados)."""
    return [p.strip() for p in os.environ.get(name, "").split(",") if p.strip()]


# Slots BRT 9/12/15/18/21 = UTC 12/15/18/21/00 (igual ReelIfy)
SLOTS_UTC = [(12, 0), (15, 0), (18, 0), (21, 0), (0, 0)]

# Longos 10+ min (YouTube): 3/dia encaixados entre os 5 shorts.
# UTC 13:30/16:30/19:30 = BRT 10:30/13:30/16:30.
LONGO_SLOTS_UTC = [(13, 30), (16, 30), (19, 30)]
LONGO_ALVO = env_int("LONGO_ALVO", 600)
LONGO_PAD = env_int("LONGO_PAD", 240)
LONGO_MAX = env_int("LONGO_MAX", 900)
LONGO_MAX_DIA = env_int("LONGO_MAX_DIA", 3)
LONGO_MIN_VIEWS = env_int("LONGO_MIN_VIEWS", 30)
LONGO_THUMB_ESTILO = env("LONGO_THUMB_ESTILO", "clean")

SCORE_THRESHOLD = env_int("SCORE_THRESHOLD", 75)
DAILY_CAP = env_int("DAILY_CAP", 5)
MIN_VIEWERS = env_int("MIN_VIEWERS", 200)
MAX_VODS_DIA = env_int("MAX_VODS_DIA", 5)

GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.6-flash")
SCORE_MODEL = env("SCORE_MODEL", "gemini-3.5-flash-lite")
DB_PATH = Path(env("DB_PATH", "data/viraclipe.db"))
FACTORY_DATA = Path(env("FACTORY_DATA", "data/factory"))
HANDLE = "@viraclipe.oficial"

# --- Foco de conteúdo: só clipes do jogo do momento (dono 18/11) ----------
# Ex.: VIRACLIP_GAMES="Grand Theft Auto VI"
#      VIRACLIP_GAME_IDS="1867279146"          (id Twitch Helix, filtro 100%)
#      VIRACLIP_GAME_LABELS="Grand Theft Auto VI=GTA 6"  (legenda/título)
#      VIRACLIP_GAMES_UNTIL="2026-12-18"        (inclusivo; vazio = sem prazo)
#      VIRACLIP_GAME_FEED=1                     (feed global PT do jogo como reforço)
# Tudo lido em tempo de execução (dá pra ligar/desligar sem reiniciar nada).
FOCUS_TITLE_ALIASES = {
    "grand theft auto vi": r"gta\s*(?:6|vi)\b|grand\s+theft\s+auto\s*(?:6|vi)\b",
}


def focus_games() -> list[str]:
    return [g for g in env_list("VIRACLIP_GAMES") if g]


def focus_ids() -> set[str]:
    return set(env_list("VIRACLIP_GAME_IDS"))


def focus_until() -> str:
    return env("VIRACLIP_GAMES_UNTIL").strip()[:10]


def focus_active(day: str = "") -> bool:
    """True se o filtro de jogo está ligado e ainda não expirou em `day`."""
    if not focus_games() and not focus_ids():
        return False
    limite = focus_until()
    alvo = (day or _dt.date.today().isoformat())[:10]
    return not (limite and alvo > limite)


def focus_match(jogo: str = "", game_id: str = "", day: str = "") -> bool:
    """True se o clipe/VOD é do jogo do foco (fora do foco, tudo passa)."""
    if not focus_active(day):
        return True
    if game_id and str(game_id) in focus_ids():
        return True
    nome = str(jogo or "").strip().casefold()
    return bool(nome) and nome in {g.casefold() for g in focus_games()}


def focus_jogo(jogo: str = "", game_id: str = "") -> str:
    """Nome canônico: quando casou só pelo game_id, usa o nome configurado."""
    nome = str(jogo or "").strip()
    if nome:
        return nome
    if game_id and str(game_id) in focus_ids():
        nomes = focus_games()
        return nomes[0] if nomes else ""
    return ""


def game_label(jogo: str) -> str:
    """Rótulo curto p/ legenda/título (ex.: 'GTA 6'); sem mapa, o nome puro."""
    nome = str(jogo or "").strip()
    for par in env_list("VIRACLIP_GAME_LABELS"):
        if "=" in par:
            chave, valor = par.split("=", 1)
            if chave.strip().casefold() == nome.casefold() and valor.strip():
                return valor.strip()
    return nome


def game_hashtag(jogo: str) -> str:
    """Hashtag do jogo pelo rótulo curto: 'GTA 6' -> 'gta6'."""
    return "".join(ch for ch in game_label(jogo).lower() if ch.isalnum())[:30]


def focus_title_re():
    """Regex de título p/ plataforma sem game_id (YouTube): GTA 6/VI + nome."""
    partes = []
    for nome in focus_games():
        alias = FOCUS_TITLE_ALIASES.get(nome.strip().casefold())
        if alias:
            partes.append(alias)
        partes.append(_re.escape(nome))
    return _re.compile("|".join(partes), _re.IGNORECASE) if partes else None


def focus_title_match(titulo: str, day: str = "") -> bool:
    """Fallback p/ VOD sem game_id: casa só o título (ex.: 'GTA 6 ...')."""
    if not focus_active(day):
        return True
    rx = focus_title_re()
    return bool(rx and rx.search(str(titulo or "")))

