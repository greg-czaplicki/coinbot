from __future__ import annotations

import logging
import time
from uuid import uuid4

from coinbot.config import load_config
from coinbot.executor.dry_run import DryRunExecutor
from coinbot.telemetry.alerts import AlertEvaluator, AlertThresholds
from coinbot.telemetry.logging import setup_logging
from coinbot.telemetry.metrics import MetricsCollector
from coinbot.telemetry.redaction import redact_secret


def main() -> None:
    setup_logging(logging.INFO)
    cfg = load_config()
    log = logging.getLogger("coinbot.main")
    metrics = MetricsCollector()
    alerts = AlertEvaluator(AlertThresholds(p95_copy_delay_ms=800))
    correlation_id = str(uuid4())
    now_ms = int(time.time() * 1000)
    metrics.record_event_receive(correlation_id, now_ms)
    metrics.record_decision(correlation_id, now_ms + 40)
    metrics.record_order_submit(correlation_id, now_ms + 120)
    log.info(
        "coinbot_boot",
        extra={
            "extra_fields": {
                "correlation_id": correlation_id,
                "source_wallet": cfg.copy.source_wallet,
                "copy_mode": cfg.copy.copy_mode,
                "dry_run": cfg.execution.dry_run,
                "api_key": redact_secret(cfg.polymarket.api_key),
            }
        },
    )
    dry_run = DryRunExecutor().execute(
        intent=None,
        risk=None,
        correlation_id=correlation_id,
        blocked_reason="bootstrap_no_events",
    )
    metrics.record_ack(correlation_id, now_ms + 180, accepted=dry_run.sent)
    snapshot = metrics.snapshot()
    alert_state = alerts.evaluate(snapshot, ws_disconnect_s=0)
    log.info(
        "telemetry_snapshot",
        extra={
            "extra_fields": {
                "correlation_id": correlation_id,
                "copy_delay_p50_ms": snapshot.copy_delay_ms.p50 if snapshot.copy_delay_ms else None,
                "copy_delay_p95_ms": snapshot.copy_delay_ms.p95 if snapshot.copy_delay_ms else None,
                "copy_delay_p99_ms": snapshot.copy_delay_ms.p99 if snapshot.copy_delay_ms else None,
                "coalescing_efficiency": snapshot.coalescing_efficiency,
                "reject_rate": snapshot.reject_rate,
                "alert_ws_disconnect": alert_state.websocket_disconnect_breach,
                "alert_reject_spike": alert_state.reject_spike_breach,
                "alert_p95_latency": alert_state.p95_latency_breach,
            }
        },
    )


if __name__ == "__main__":
    main()
