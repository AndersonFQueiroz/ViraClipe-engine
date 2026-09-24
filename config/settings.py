"""Config central do ViraClipe (Fase 1 pós-live, tudo free)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Slots BRT 9/12/15/18/21 = UTC 12/15/18/21/00 (igual ReelIfy)
SLOTS_UTC = [(12, 0), (15, 0), (18, 0), (21, 0), (0, 0)]

SCORE_THRESHOLD = env_int("SCORE_THRESHOLD", 75)
DAILY_CAP = env_int("DAILY_CAP", 5)
MIN_VIEWERS = env_int("MIN_VIEWERS", 200)
MAX_VODS_DIA = env_int("MAX_VODS_DIA", 5)

GEMINI_MODEL = env("GEMINI_MODEL", "gemini-2.5-flash")
DB_PATH = Path(env("DB_PATH", "data/viraclipe.db"))
FACTORY_DATA = Path(env("FACTORY_DATA", "data/factory"))
HANDLE = "@ViraClipe"
