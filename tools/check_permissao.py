"""Triagem 'cortes liberados' na bio/descrição do streamer."""
from __future__ import annotations

import sys

from factory.discovery import tem_permissao


def main(argv: list[str]) -> int:
    texto = " ".join(argv[1:]) if len(argv) > 1 else sys.stdin.read()
    ok = tem_permissao(texto)
    print("LIBERADO" if ok else "SEM-EVIDENCIA")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
