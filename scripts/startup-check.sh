#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f ".env" ]]; then
  echo "missing .env"
  exit 1
fi

if [[ ! -d "src/coinbot" ]]; then
  echo "missing source tree"
  exit 1
fi

python3 - <<'PY'
import os
from pathlib import Path

required = [
    "COPY_SOURCE_WALLET",
    "COPY_MODE",
    "EXECUTION_DRY_RUN",
]

env_path = Path(".env")
values = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    values[k.strip()] = v.strip()

missing = [k for k in required if not values.get(k)]
if missing:
    raise SystemExit("missing env keys: " + ",".join(missing))
PY

echo "startup checks passed"
