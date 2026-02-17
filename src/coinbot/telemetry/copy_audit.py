from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CopyAuditConfig:
    out_dir: str = "runs/telemetry"
    jsonl_name: str = "copy_audit.jsonl"


class CopyAuditLogger:
    def __init__(self, cfg: CopyAuditConfig = CopyAuditConfig()) -> None:
        self._path = Path(cfg.out_dir) / cfg.jsonl_name
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, row: dict[str, Any]) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **row}
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(_coerce(payload), separators=(",", ":")) + "\n")


def _coerce(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, Decimal):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.astimezone(timezone.utc).isoformat()
        else:
            out[key] = value
    return out
