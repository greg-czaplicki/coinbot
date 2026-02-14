from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExportConfig:
    out_dir: str = "runs/telemetry"
    csv_name: str = "snapshots.csv"
    jsonl_name: str = "snapshots.jsonl"


class TelemetryExporter:
    def __init__(self, cfg: ExportConfig = ExportConfig()) -> None:
        self._cfg = cfg
        self._out_dir = Path(cfg.out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = self._out_dir / cfg.csv_name
        self._jsonl_path = self._out_dir / cfg.jsonl_name
        self._ensure_csv_header()

    def write_snapshot(self, row: dict[str, Any]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        payload = {"ts": ts, **row}
        with self._jsonl_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, separators=(",", ":")) + "\n")

        with self._csv_path.open("a", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=_FIELDS)
            writer.writerow(_coerce_row(payload))

    def _ensure_csv_header(self) -> None:
        if self._csv_path.exists():
            return
        with self._csv_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=_FIELDS)
            writer.writeheader()


_FIELDS = [
    "ts",
    "copy_delay_p50_ms",
    "copy_delay_p95_ms",
    "copy_delay_p99_ms",
    "source_fills",
    "destination_orders",
    "coalescing_efficiency",
    "reject_rate",
    "alert_ws_disconnect",
    "alert_reject_spike",
    "alert_p95_latency",
    "kill_switch_active",
    "kill_switch_reason",
    "realized_pnl_usd",
    "realized_settled_pnl_usd",
    "unrealized_pnl_usd",
    "fees_usd",
    "net_pnl_usd",
]


def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key in _FIELDS:
        value = row.get(key)
        if isinstance(value, bool):
            coerced[key] = "true" if value else "false"
        elif value is None:
            coerced[key] = ""
        else:
            coerced[key] = str(value)
    return coerced
