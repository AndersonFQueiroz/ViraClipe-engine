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
