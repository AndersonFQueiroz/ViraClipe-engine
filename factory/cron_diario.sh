#!/usr/bin/env bash
# Cron diário ViraClipe — 08h BRT (11h UTC). RODA LOCAL (bot+banco+arquivos).
# Fonte A auto-posta; fonte B manda prévias p/ aprovar no Telegram.
# Termux/crontab: 0 11 * * * cd /caminho/ViraClipe && ./factory/cron_diario.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && source .env
set +a
mkdir -p data/logs
python3 tools/dia.py --max 2 >> "data/logs/cron-$(date +%F).log" 2>&1
