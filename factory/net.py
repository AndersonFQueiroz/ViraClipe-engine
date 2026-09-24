"""Retry com backoff + jitter p/ rede da fábrica (port ReelIfy).

Só repete erro transitório (timeout/conexão/5xx/429). Erro de negócio falha na hora.
"""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

import requests

T = TypeVar("T")
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException, response=None) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and response is not None:
        try:
            return response.status_code in RETRYABLE_STATUS
        except Exception:
            return False
    return False


def call(func: Callable[..., T], *args, tries: int = 3, base: float = 4.0, **kwargs) -> T:
    last: BaseException | None = None
    response = None
    for attempt in range(tries):
        try:
            return func(*args, **kwargs)
        except requests.HTTPError as exc:
            response = exc.response
            last = exc
            if not _is_retryable(exc, response):
                raise
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
        except Exception:
            raise
        if attempt < tries - 1:
            time.sleep(base * 2**attempt + random.uniform(0, 1))
    assert last is not None
    raise last


_LLM_RETRYABLE = ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded", "high demand")


def llm_retryable(exc: BaseException) -> bool:
    s = f"{type(exc).__name__} {exc}"
    return any(k in s for k in _LLM_RETRYABLE)


def llm_call(fn: Callable[[], T], tries: int = 2, wait: float = 20.0) -> T:
    """1 retry p/ 429/503 do Gemini free. Não-retryable falha na hora."""
    last: BaseException | None = None
    for i in range(max(1, tries)):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not llm_retryable(exc):
                raise
            time.sleep(wait)
    assert last is not None
    raise last


def _is_quota(exc: BaseException) -> bool:
    s = f"{exc}"
    return "429" in s or "RESOURCE_EXHAUSTED" in s


def llm_keys(first_key: str = "") -> list[str]:
    """Pool de chaves: principal + GEMINI_API_KEYS (vírgula). Sem duplicar."""
    import os as _os

    keys = [first_key.strip()] if first_key and first_key.strip() else []
    for k in _os.environ.get("GEMINI_API_KEYS", "").split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def llm_with_keys(make_call: Callable[[str], T], first_key: str = "", wait: float = 20.0) -> T:
    """Roda make_call(key) rotacionando chaves em 429 (quota).

    429/RESOURCE_EXHAUSTED pula p/ próxima chave sem gastar retry;
    503/transiente dá 1 retry na mesma chave. Não-retryable falha na hora.
    """
    keys = llm_keys(first_key) or [""]
    last: BaseException | None = None
    for key in keys:
        for attempt in range(2):
            try:
                return make_call(key)
            except Exception as exc:
                last = exc
                if not llm_retryable(exc):
                    raise
                if _is_quota(exc):
                    break  # quota desta chave: tenta a próxima
                time.sleep(wait)
    assert last is not None
    raise last


def post(session: requests.Session, url: str, **kwargs) -> requests.Response:
    def _do() -> requests.Response:
        r = session.post(url, **kwargs)
        r.raise_for_status()
        return r

    return call(_do)


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    def _do() -> requests.Response:
        r = session.get(url, **kwargs)
        r.raise_for_status()
        return r

    return call(_do)
