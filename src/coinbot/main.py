from __future__ import annotations

import logging
from uuid import uuid4

from coinbot.config import load_config
from coinbot.executor.dry_run import DryRunExecutor
from coinbot.telemetry.logging import setup_logging


def main() -> None:
    setup_logging(logging.INFO)
    cfg = load_config()
    log = logging.getLogger("coinbot.main")
    correlation_id = str(uuid4())
    log.info(
        "coinbot_boot",
        extra={
            "extra_fields": {
                "correlation_id": correlation_id,
                "source_wallet": cfg.copy.source_wallet,
                "copy_mode": cfg.copy.copy_mode,
                "dry_run": cfg.execution.dry_run,
            }
        },
    )
    DryRunExecutor().execute(
        intent=None,
        risk=None,
        correlation_id=correlation_id,
        blocked_reason="bootstrap_no_events",
    )


if __name__ == "__main__":
    main()
