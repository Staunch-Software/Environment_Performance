#!/usr/bin/env bash
# Daily fuel-consumption extraction — runs both scrapers back to back.
# Intended to be triggered by cron on the deployment VM.
set -euo pipefail

BACKEND_DIR="/path/to/Environment_Performance/backend"   # <-- set this to the real path on the VM
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"
LOG_DIR="$BACKEND_DIR/logs"
LOCK_FILE="/tmp/fuel_scrapers.lock"

mkdir -p "$LOG_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)

# Prevent overlapping runs if a previous invocation is still going.
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "$(date) - previous run still in progress, skipping" >> "$LOG_DIR/fuel_scrapers.log"
    exit 0
fi

cd "$BACKEND_DIR"

echo "=== $(date) : WNI fuel scraper start ===" >> "$LOG_DIR/wni_$STAMP.log"
"$VENV_PYTHON" -m scrapers.wni_fuel_scraper >> "$LOG_DIR/wni_$STAMP.log" 2>&1
echo "=== $(date) : WNI fuel scraper end ===" >> "$LOG_DIR/wni_$STAMP.log"

echo "=== $(date) : MariApps fuel scraper start ===" >> "$LOG_DIR/mariapps_$STAMP.log"
"$VENV_PYTHON" -m scrapers.mariapps_fuel_scraper >> "$LOG_DIR/mariapps_$STAMP.log" 2>&1
echo "=== $(date) : MariApps fuel scraper end ===" >> "$LOG_DIR/mariapps_$STAMP.log"
