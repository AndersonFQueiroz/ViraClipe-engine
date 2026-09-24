"""Gera valores GH Secrets do modo full a partir de data/private/ (nunca commitado).

Uso:
  mkdir -p data/private
  # edite: prompt_full.txt, blocklist_full.txt (1 termo/linha), pack_full.json
  python3 -m tools.make_private_secrets

Saída: só no terminal (copie p/ GH Secrets). Nunca escreve em repo público.
data/private/ está no .gitignore.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIV = ROOT / "data" / "private"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def main() -> int:
    if not PRIV.exists():
        print(f" crie {PRIV}/ com prompt_full.txt, blocklist_full.txt, pack_full.json")
        return 1
    prompt = (PRIV / "prompt_full.txt").read_text(encoding="utf-8") if (PRIV / "prompt_full.txt").exists() else ""
    block = (PRIV / "blocklist_full.txt").read_text(encoding="utf-8") if (PRIV / "blocklist_full.txt").exists() else ""
    pack = (PRIV / "pack_full.json").read_text(encoding="utf-8") if (PRIV / "pack_full.json").exists() else "{}"
    try:
        json.loads(pack or "{}")
    except Exception as exc:
        print(f"pack_full.json inválido: {exc}")
        return 1
    print("# Cole cada bloco num GH Secret (Settings > Secrets > Actions):")
    print(f"\n## VIRACLIP_PROMPT_B64 ({len(prompt)} chars)\n{_b64(prompt)[:4000]}" if prompt else "\n## VIRACLIP_PROMPT_B64: (vazio — crie data/private/prompt_full.txt)")
    if prompt and len(_b64(prompt)) > 4000:
        print(f"# ... +{len(_b64(prompt)) - 4000} chars (total {len(_b64(prompt))}). GH Secret aceita até 48KB, ok.")
        print(_b64(prompt)[4000:8000])
    print(f"\n## VIRACLIP_BLOCKLIST_B64 ({len(block)} chars)\n{_b64(block)}" if block else "\n## VIRACLIP_BLOCKLIST_B64: (vazio)")
    print(f"\n## VIRACLIP_PACK_JSON_B64 ({len(pack)} chars)\n{_b64(pack)}" if pack.strip() not in ("", "{}") else "\n## VIRACLIP_PACK_JSON_B64: (vazio)")
    print("\n# Pesos afinados (GH Variables ou env, não precisam ser segredo):")
    print("SCORE_W_CHAT=0.5\nSCORE_W_AUDIO=0.2\nSCORE_W_LLM=0.3\nSIGNAL_W_CHAT=0.7\nSIGNAL_W_AUDIO=0.3")
    print("\n# NUNCA commite data/private/ — já está no .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
