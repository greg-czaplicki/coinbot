#!/usr/bin/env bash
set -euo pipefail

RUN_MINUTES="${1:-30}"
OUT_DIR="${2:-runs}"
mkdir -p "$OUT_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="$OUT_DIR/paper_${ts}.log"

echo "Starting paper session for ${RUN_MINUTES}m"
echo "Log file: $log_file"

export EXECUTION_DRY_RUN=true
timeout "${RUN_MINUTES}m" env PYTHONPATH=src python3 -m coinbot.main | tee "$log_file" || true

echo "Session complete: $log_file"
