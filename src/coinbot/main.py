from __future__ import annotations

import logging
import time
from decimal import Decimal
from queue import Empty, Queue
from threading import Thread
from uuid import uuid4

from coinbot.config import load_config
from coinbot.decision_engine.kill_switch import AutoKillGuard, AutoKillThresholds, KillSwitch
from coinbot.decision_engine.policy import IntentPolicy, WindowRiskTracker
from coinbot.executor.dry_run import DryRunExecutor
from coinbot.executor.order_client import ClobOrderClient
from coinbot.schemas import ExecutionIntent, TradeEvent
from coinbot.telemetry.alerts import AlertEvaluator, AlertThresholds
from coinbot.telemetry.logging import setup_logging
from coinbot.telemetry.metrics import MetricsCollector
from coinbot.telemetry.redaction import redact_secret
from coinbot.watcher.source_activity import ActivityPollerConfig, SourceWalletActivityPoller
from coinbot.state_store.checkpoints import SqliteCheckpointStore
from coinbot.state_store.dedupe import SqliteDedupeStore


def main() -> None:
    setup_logging(logging.INFO)
    cfg = load_config()
    log = logging.getLogger("coinbot.main")
    metrics = MetricsCollector()
    alerts = AlertEvaluator(AlertThresholds(p95_copy_delay_ms=800))
    dry_run = DryRunExecutor()
    order_client = ClobOrderClient(cfg.polymarket, cfg.execution)
    policy = IntentPolicy(cfg.sizing, cfg.execution)
    risk_tracker = WindowRiskTracker(cfg.sizing)
    kill_switch = KillSwitch()
    auto_kill = AutoKillGuard(
        kill_switch,
        AutoKillThresholds(max_error_rate=0.2, max_p95_latency_ms=1200),
    )
    dedupe = SqliteDedupeStore()
    checkpoints = SqliteCheckpointStore()
    queue: Queue[TradeEvent] = Queue(maxsize=5000)

    log.info(
        "coinbot_boot",
        extra={
            "extra_fields": {
                "correlation_id": str(uuid4()),
                "source_wallet": cfg.copy.source_wallet,
                "copy_mode": cfg.copy.copy_mode,
                "dry_run": cfg.execution.dry_run,
                "api_key": redact_secret(cfg.polymarket.api_key),
            }
        },
    )

    def _enqueue(event: TradeEvent) -> None:
        try:
            queue.put(event, timeout=1)
        except Exception:
            log.warning("event_queue_full event_id=%s", event.event_id)

    poller = SourceWalletActivityPoller(
        ActivityPollerConfig(
            data_api_url=cfg.polymarket.data_api_url,
            source_wallet=cfg.copy.source_wallet,
        ),
        dedupe=dedupe,
        checkpoints=checkpoints,
        on_trade_event=_enqueue,
    )
    poller_thread = Thread(target=poller.run_forever, name="source-poller", daemon=True)
    poller_thread.start()

    last_snapshot_s = 0.0
    while True:
        try:
            event = queue.get(timeout=2)
            correlation_id = event.event_id or str(uuid4())
            now_ms = int(time.time() * 1000)
            metrics.record_event_receive(correlation_id, now_ms)

            if kill_switch.check().active:
                dry_run.execute(
                    intent=None,
                    risk=None,
                    correlation_id=correlation_id,
                    blocked_reason=kill_switch.check().reason,
                )
                continue

            raw_intent = ExecutionIntent(
                intent_id=f"{event.market_id}:{event.outcome}:{correlation_id}",
                market_id=event.market_id,
                outcome=event.outcome,
                side=event.side,
                target_notional_usd=event.notional_usd,
                max_slippage_bps=cfg.execution.max_slippage_bps,
                coalesced_event_ids=(event.event_id,),
                window_id=event.window.window_id if event.window else None,
            )

            decision = policy.apply(raw_intent, [event])
            metrics.record_decision(correlation_id, int(time.time() * 1000))
            if decision.intent is None:
                dry_run.execute(
                    intent=None,
                    risk=None,
                    correlation_id=correlation_id,
                    blocked_reason=decision.blocked_reason,
                )
                continue

            risk = risk_tracker.check_and_apply(decision.intent)
            if risk.blocked:
                dry_run.execute(
                    intent=None,
                    risk=risk,
                    correlation_id=correlation_id,
                    blocked_reason=risk.blocked_reason,
                )
                continue

            metrics.record_order_submit(correlation_id, int(time.time() * 1000))
            px = max(event.price, Decimal("0.01"))
            size = (decision.intent.target_notional_usd / px).quantize(Decimal("0.0001"))
            submission = order_client.submit_marketable_limit(intent=decision.intent, price=px, size=size)
            metrics.record_ack(correlation_id, int(time.time() * 1000), accepted=submission.accepted)
            dry_run.execute(intent=decision.intent, risk=risk, correlation_id=correlation_id)

        except Empty:
            pass

        now_s = time.time()
        if now_s - last_snapshot_s >= 30:
            snapshot = metrics.snapshot()
            alert_state = alerts.evaluate(snapshot, ws_disconnect_s=0)
            auto_kill.evaluate(
                error_rate=snapshot.reject_rate,
                p95_latency_ms=int(snapshot.copy_delay_ms.p95 if snapshot.copy_delay_ms else 0),
            )
            log.info(
                "telemetry_snapshot",
                extra={
                    "extra_fields": {
                        "copy_delay_p50_ms": snapshot.copy_delay_ms.p50 if snapshot.copy_delay_ms else None,
                        "copy_delay_p95_ms": snapshot.copy_delay_ms.p95 if snapshot.copy_delay_ms else None,
                        "copy_delay_p99_ms": snapshot.copy_delay_ms.p99 if snapshot.copy_delay_ms else None,
                        "source_fills": snapshot.source_fills,
                        "destination_orders": snapshot.destination_orders,
                        "coalescing_efficiency": snapshot.coalescing_efficiency,
                        "reject_rate": snapshot.reject_rate,
                        "alert_ws_disconnect": alert_state.websocket_disconnect_breach,
                        "alert_reject_spike": alert_state.reject_spike_breach,
                        "alert_p95_latency": alert_state.p95_latency_breach,
                        "kill_switch_active": kill_switch.check().active,
                        "kill_switch_reason": kill_switch.check().reason,
                    }
                },
            )
            last_snapshot_s = now_s


if __name__ == "__main__":
    main()
