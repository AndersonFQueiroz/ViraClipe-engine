#!/usr/bin/env bash
# Cron diário ViraClipe — 08h BRT (11h UTC).
# Termux/crontab: 0 11 * * * cd /caminho/ViraClipe && ./factory/cron_diario.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && source .env
set +a
mkdir -p data/logs
python3 -m factory.run_diaria >> "data/logs/cron-$(date +%F).log" 2>&1
