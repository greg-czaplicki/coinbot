from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class ShadowLogConfig:
    out_dir: str = "runs/telemetry"
    jsonl_name: str = "shadow_decisions.jsonl"


class ShadowDecisionLogger:
    def __init__(self, cfg: ShadowLogConfig = ShadowLogConfig()) -> None:
        self._path = Path(cfg.out_dir) / cfg.jsonl_name
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        correlation_id: str,
        market_id: str,
        window_id: str | None,
        target_notional_usd: Decimal,
        blocked_reason: str,
        executed: bool,
    ) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id,
            "market_id": market_id,
            "window_id": window_id or "",
            "target_notional_usd": str(target_notional_usd),
            "blocked_reason": blocked_reason,
            "executed": executed,
        }
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, separators=(",", ":")) + "\n")
