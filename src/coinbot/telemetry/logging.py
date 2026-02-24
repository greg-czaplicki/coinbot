from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, separators=(",", ":"))


class ConciseFilter(logging.Filter):
    _ALLOWED_MESSAGES = {
        "coinbot_boot",
        "source_activity_disabled",
        "source_ws_enabled",
        "auto_redeemer_enabled",
        "redeemer_started",
        "redeemer_redeemed",
        "redeemer_redeemed_safe",
        "order_submitted",
        "order_rejected",
        "pnl_settlement_applied",
        "telemetry_snapshot",
        "shutdown_signal",
        "coinbot_shutdown_complete",
    }
    _NOISY_PREFIXES = (
        "ws_recv_progress",
        "ws_recv_sample",
        "ws_subscribe",
        "ws_connected",
        "activity_ws_stats",
        "ws_source_stats",
        "ws_message_sample",
        "ws_trade_no_wallet_match",
        "cross_source_duplicate_drop",
        "dry_run_blocked",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        if msg in self._ALLOWED_MESSAGES:
            return True
        if msg.startswith(self._NOISY_PREFIXES):
            return False
        return False


def setup_logging(level: int = logging.INFO, profile: str = "verbose") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    if profile == "concise":
        handler.addFilter(ConciseFilter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
