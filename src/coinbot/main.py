from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from queue import Empty, Queue
from threading import Event, Thread
from uuid import uuid4

from coinbot.config import AppConfig, load_config
from coinbot.decision_engine.kill_switch import AutoKillGuard, AutoKillThresholds, KillSwitch
from coinbot.decision_engine.policy import IntentPolicy, WindowRiskTracker
from coinbot.executor.dry_run import DryRunExecutor
from coinbot.executor.market_cache import MarketMetadataCache
from coinbot.executor.order_client import ClobOrderClient
from coinbot.schemas import ExecutionIntent, Side, TradeEvent
from coinbot.telemetry.alerts import AlertEvaluator, AlertThresholds
from coinbot.telemetry.exporter import TelemetryExporter
from coinbot.telemetry.logging import setup_logging
from coinbot.telemetry.metrics import MetricsCollector
from coinbot.telemetry.pnl import PnLTracker
from coinbot.telemetry.redaction import redact_secret
from coinbot.telemetry.copy_audit import CopyAuditLogger
from coinbot.telemetry.shadow import ShadowDecisionLogger
from coinbot.watcher.source_activity import ActivityPollerConfig, SourceWalletActivityPoller
from coinbot.watcher.source_ws import SourceWalletWsWatcher
from coinbot.state_store.checkpoints import SqliteCheckpointStore
from coinbot.state_store.dedupe import SqliteDedupeStore


@dataclass
class CoalesceBucket:
    events: list[TradeEvent] = field(default_factory=list)
    first_seen_ms: int = 0


def main() -> None:
    setup_logging(logging.INFO)
    cfg = load_config()
    log = logging.getLogger("coinbot.main")
    metrics = MetricsCollector()
    alerts = AlertEvaluator(AlertThresholds(p95_copy_delay_ms=800))
    exporter = TelemetryExporter()
    shadow = ShadowDecisionLogger()
    copy_audit = CopyAuditLogger()
    dry_run = DryRunExecutor()
    market_cache = MarketMetadataCache(cfg.polymarket)
    order_client = ClobOrderClient(cfg.polymarket, cfg.execution, market_cache=market_cache)
    policy = IntentPolicy(cfg.sizing, cfg.execution)
    risk_tracker = WindowRiskTracker(cfg.sizing)
    pnl = PnLTracker(fee_bps=Decimal(str(cfg.execution.fee_bps)))
    kill_switch = KillSwitch()
    auto_kill = AutoKillGuard(
        kill_switch,
        AutoKillThresholds(
            max_error_rate=float(os.getenv("AUTO_KILL_MAX_ERROR_RATE", "0.2")),
            max_p95_latency_ms=int(os.getenv("AUTO_KILL_MAX_P95_LATENCY_MS", "1200")),
            recover_max_error_rate=float(os.getenv("AUTO_KILL_RECOVER_MAX_ERROR_RATE", "0.1")),
            recover_max_p95_latency_ms=int(os.getenv("AUTO_KILL_RECOVER_MAX_P95_LATENCY_MS", "800")),
            recovery_consecutive_snapshots=int(
                os.getenv("AUTO_KILL_RECOVERY_CONSECUTIVE_SNAPSHOTS", "2")
            ),
        ),
    )
    dedupe = SqliteDedupeStore()
    checkpoints = SqliteCheckpointStore()
    queue: Queue[TradeEvent] = Queue(maxsize=5000)
    buckets: dict[str, CoalesceBucket] = {}
    event_receive_ms_by_id: dict[str, int] = {}
    stop_event = Event()

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
        market_cache.warm([event.market_slug, event.market_id])
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
    if cfg.copy.source_ws_enabled:
        ws_watcher = SourceWalletWsWatcher(
            ws_url=cfg.polymarket.ws_url,
            source_wallet=cfg.copy.source_wallet,
            on_trade_event=_enqueue,
        )
        ws_thread = Thread(target=ws_watcher.run_forever, name="source-ws", daemon=True)
        ws_thread.start()
        log.info("source_ws_enabled url=%s", cfg.polymarket.ws_url)

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("shutdown_signal signum=%s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    last_snapshot_s = 0.0
    while not stop_event.is_set():
        try:
            event = queue.get(timeout=0.1)
            correlation_id = event.event_id or str(uuid4())
            now_ms = int(time.time() * 1000)
            metrics.record_event_receive(correlation_id, now_ms)
            event_receive_ms_by_id[event.event_id] = now_ms
            pnl_market_id = event.market_slug or event.market_id
            pnl.set_mark(pnl_market_id, event.outcome, event.price)

            key = _coalesce_key(event, net_opposite=cfg.copy.net_opposite_trades)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = CoalesceBucket(events=[event], first_seen_ms=now_ms)
                buckets[key] = bucket
            else:
                bucket.events.append(event)

        except Empty:
            pass

        due_keys = [
            key
            for key, bucket in buckets.items()
            if int(time.time() * 1000) - bucket.first_seen_ms >= cfg.copy.coalesce_ms
        ]
        for key in due_keys:
            bucket = buckets.pop(key)
            process_start_ns = time.perf_counter_ns()
            coalesce_wait_ms = max(0.0, float(int(time.time() * 1000) - bucket.first_seen_ms))
            policy_ms = 0.0
            risk_ms = 0.0
            submit_ms = 0.0
            coalesced = _coalesced_intent(bucket.events, max_slippage_bps=cfg.execution.max_slippage_bps)
            if coalesced is None:
                continue
            intent, source_events = coalesced
            correlation_id = intent.coalesced_event_ids[0] if intent.coalesced_event_ids else str(uuid4())
            source_last = source_events[-1]
            source_path = source_last.source_path or "unknown"
            source_abs_notional = sum(abs(event.notional_usd) for event in source_events)
            source_last_receive_ms = event_receive_ms_by_id.get(source_last.event_id, int(time.time() * 1000))
            source_exec_to_receive_ms = max(
                0.0,
                (source_last.received_ts - source_last.executed_ts).total_seconds() * 1000,
            )
            source_emit_to_receive_ms = max(
                0.0,
                float(source_last_receive_ms - int(source_last.received_ts.timestamp() * 1000)),
            )
            source_receive_to_submit_ms = int(
                (datetime.now(source_last.received_ts.tzinfo) - source_last.received_ts).total_seconds() * 1000
            )
            source_exec_to_submit_ms = int(
                (datetime.now(source_last.executed_ts.tzinfo) - source_last.executed_ts).total_seconds() * 1000
            )

            def _source_timing_fields() -> dict[str, float | int | str]:
                return {
                    "source_exec_to_fetch_ms": (
                        round(source_last.source_exec_to_fetch_ms, 3)
                        if source_last.source_exec_to_fetch_ms is not None
                        else ""
                    ),
                    "source_fetch_to_emit_ms": (
                        round(source_last.source_fetch_to_emit_ms, 3)
                        if source_last.source_fetch_to_emit_ms is not None
                        else ""
                    ),
                    "source_emit_to_receive_ms": round(source_emit_to_receive_ms, 3),
                    "source_poll_cycle_ms": (
                        round(source_last.source_poll_cycle_ms, 3)
                        if source_last.source_poll_cycle_ms is not None
                        else ""
                    ),
                }

            for source_event in source_events:
                event_receive_ms_by_id.pop(source_event.event_id, None)

            def _stage_fields() -> dict[str, float | str]:
                return {
                    "stage_coalesce_wait_ms": coalesce_wait_ms,
                    "stage_policy_ms": round(policy_ms, 3) if policy_ms > 0 else "",
                    "stage_risk_ms": round(risk_ms, 3) if risk_ms > 0 else "",
                    "stage_submit_ms": round(submit_ms, 3) if submit_ms > 0 else "",
                    "stage_total_pipeline_ms": round(
                        max(0.0, (time.perf_counter_ns() - process_start_ns) / 1_000_000), 3
                    ),
                }

            if kill_switch.check().active:
                dry_run.execute(
                    intent=None,
                    risk=None,
                    correlation_id=correlation_id,
                    blocked_reason=kill_switch.check().reason,
                )
                copy_audit.write(
                    {
                        "correlation_id": correlation_id,
                        "market_id": intent.market_id,
                        "source_path": source_path,
                        "window_id": intent.window_id or "",
                        "outcome": intent.outcome,
                        "side": intent.side.value,
                        "source_events": len(source_events),
                        "source_last_price": source_last.price,
                        "source_net_notional_usd": intent.target_notional_usd,
                        "source_abs_notional_usd": source_abs_notional,
                        "source_exec_to_receive_ms": round(source_exec_to_receive_ms, 3),
                        "source_exec_to_submit_ms": source_exec_to_submit_ms,
                        "source_receive_to_submit_ms": source_receive_to_submit_ms,
                        **_source_timing_fields(),
                        "bot_target_notional_usd": "",
                        "bot_price": "",
                        "bot_size": "",
                        "size_ratio_vs_source_net": "",
                        "submitted": False,
                        "executed": False,
                        "blocked_reason": kill_switch.check().reason,
                        "submit_status": "",
                        "submit_error_code": "",
                        **_stage_fields(),
                    }
                )
                shadow.write(
                    correlation_id=correlation_id,
                    market_id=intent.market_id,
                    window_id=intent.window_id,
                    target_notional_usd=intent.target_notional_usd,
                    blocked_reason=kill_switch.check().reason,
                    executed=False,
                )
                continue

            policy_start_ns = time.perf_counter_ns()
            decision = policy.apply(intent, source_events)
            policy_ms = (time.perf_counter_ns() - policy_start_ns) / 1_000_000
            metrics.record_decision(correlation_id, int(time.time() * 1000))
            if decision.intent is None:
                dry_run.execute(
                    intent=None,
                    risk=None,
                    correlation_id=correlation_id,
                    blocked_reason=decision.blocked_reason,
                )
                copy_audit.write(
                    {
                        "correlation_id": correlation_id,
                        "market_id": intent.market_id,
                        "source_path": source_path,
                        "window_id": intent.window_id or "",
                        "outcome": intent.outcome,
                        "side": intent.side.value,
                        "source_events": len(source_events),
                        "source_last_price": source_last.price,
                        "source_net_notional_usd": intent.target_notional_usd,
                        "source_abs_notional_usd": source_abs_notional,
                        "source_exec_to_receive_ms": round(source_exec_to_receive_ms, 3),
                        "source_exec_to_submit_ms": source_exec_to_submit_ms,
                        "source_receive_to_submit_ms": source_receive_to_submit_ms,
                        **_source_timing_fields(),
                        "bot_target_notional_usd": "",
                        "bot_price": "",
                        "bot_size": "",
                        "size_ratio_vs_source_net": "",
                        "submitted": False,
                        "executed": False,
                        "blocked_reason": decision.blocked_reason,
                        "submit_status": "",
                        "submit_error_code": "",
                        **_stage_fields(),
                    }
                )
                shadow.write(
                    correlation_id=correlation_id,
                    market_id=intent.market_id,
                    window_id=intent.window_id,
                    target_notional_usd=intent.target_notional_usd,
                    blocked_reason=decision.blocked_reason,
                    executed=False,
                )
                continue

            risk_start_ns = time.perf_counter_ns()
            risk = risk_tracker.check_and_apply(decision.intent)
            risk_ms = (time.perf_counter_ns() - risk_start_ns) / 1_000_000
            if risk.blocked:
                dry_run.execute(
                    intent=None,
                    risk=risk,
                    correlation_id=correlation_id,
                    blocked_reason=risk.blocked_reason,
                )
                copy_audit.write(
                    {
                        "correlation_id": correlation_id,
                        "market_id": decision.intent.market_id,
                        "source_path": source_path,
                        "window_id": decision.intent.window_id or "",
                        "outcome": decision.intent.outcome,
                        "side": decision.intent.side.value,
                        "source_events": len(source_events),
                        "source_last_price": source_last.price,
                        "source_net_notional_usd": intent.target_notional_usd,
                        "source_abs_notional_usd": source_abs_notional,
                        "source_exec_to_receive_ms": round(source_exec_to_receive_ms, 3),
                        "source_exec_to_submit_ms": source_exec_to_submit_ms,
                        "source_receive_to_submit_ms": source_receive_to_submit_ms,
                        **_source_timing_fields(),
                        "bot_target_notional_usd": decision.intent.target_notional_usd,
                        "bot_price": "",
                        "bot_size": "",
                        "size_ratio_vs_source_net": (
                            float(decision.intent.target_notional_usd / intent.target_notional_usd)
                            if intent.target_notional_usd > 0
                            else ""
                        ),
                        "submitted": False,
                        "executed": False,
                        "blocked_reason": risk.blocked_reason,
                        "submit_status": "",
                        "submit_error_code": "",
                        **_stage_fields(),
                    }
                )
                shadow.write(
                    correlation_id=correlation_id,
                    market_id=decision.intent.market_id,
                    window_id=decision.intent.window_id,
                    target_notional_usd=decision.intent.target_notional_usd,
                    blocked_reason=risk.blocked_reason,
                    executed=False,
                )
                continue

            metrics.record_order_submit(correlation_id, int(time.time() * 1000))
            px = max(source_events[-1].price, Decimal("0.01"))
            size = (decision.intent.target_notional_usd / px).quantize(Decimal("0.0001"))
            submit_start_ns = time.perf_counter_ns()
            submission = order_client.submit_marketable_limit(
                intent=decision.intent,
                price=px,
                size=size,
                market_slug=source_events[-1].market_slug,
            )
            submit_ms = (time.perf_counter_ns() - submit_start_ns) / 1_000_000
            counts_toward_reject_rate = submission.error_code != "min_size"
            metrics.record_ack(
                correlation_id,
                int(time.time() * 1000),
                accepted=submission.accepted,
                counts_toward_reject_rate=counts_toward_reject_rate,
            )
            if submission.accepted:
                pnl_market_id = source_events[-1].market_slug or decision.intent.market_id
                pnl.apply_fill(
                    market_id=pnl_market_id,
                    outcome=decision.intent.outcome,
                    side=decision.intent.side.value,
                    qty=size,
                    price=px,
                )
            dry_run.execute(intent=decision.intent, risk=risk, correlation_id=correlation_id)
            copy_audit.write(
                {
                    "correlation_id": correlation_id,
                    "market_id": decision.intent.market_id,
                    "source_path": source_path,
                    "window_id": decision.intent.window_id or "",
                    "outcome": decision.intent.outcome,
                    "side": decision.intent.side.value,
                    "source_events": len(source_events),
                    "source_last_price": source_last.price,
                    "source_net_notional_usd": intent.target_notional_usd,
                    "source_abs_notional_usd": source_abs_notional,
                    "source_exec_to_receive_ms": round(source_exec_to_receive_ms, 3),
                    "source_exec_to_submit_ms": source_exec_to_submit_ms,
                    "source_receive_to_submit_ms": source_receive_to_submit_ms,
                    **_source_timing_fields(),
                    "bot_target_notional_usd": decision.intent.target_notional_usd,
                    "bot_price": px,
                    "bot_size": size,
                    "size_ratio_vs_source_net": (
                        float(decision.intent.target_notional_usd / intent.target_notional_usd)
                        if intent.target_notional_usd > 0
                        else ""
                    ),
                    "submitted": True,
                    "executed": submission.accepted,
                    "blocked_reason": "",
                    "submit_status": submission.status,
                    "submit_error_code": submission.error_code,
                    **_stage_fields(),
                }
            )
            shadow.write(
                correlation_id=correlation_id,
                market_id=decision.intent.market_id,
                window_id=decision.intent.window_id,
                target_notional_usd=decision.intent.target_notional_usd,
                blocked_reason=(
                    ""
                    if submission.accepted
                    else (
                        "exchange_min_size_reject"
                        if submission.error_code == "min_size"
                        else "order_rejected"
                    )
                ),
                executed=submission.accepted,
            )

        now_s = time.time()
        if now_s - last_snapshot_s >= 30:
            _emit_snapshot(
                cfg=cfg,
                log=log,
                metrics=metrics,
                alerts=alerts,
                auto_kill=auto_kill,
                kill_switch=kill_switch,
                pnl=pnl,
                market_cache=market_cache,
                exporter=exporter,
            )
            last_snapshot_s = now_s

    _emit_snapshot(
        cfg=cfg,
        log=log,
        metrics=metrics,
        alerts=alerts,
        auto_kill=auto_kill,
        kill_switch=kill_switch,
        pnl=pnl,
        market_cache=market_cache,
        exporter=exporter,
        final=True,
    )
    log.info("coinbot_shutdown_complete")


def _coalesce_key(event: TradeEvent, *, net_opposite: bool) -> str:
    window_id = event.window.window_id if event.window else "na"
    if net_opposite:
        return f"{event.market_id}:{window_id}:{event.outcome}"
    return f"{event.market_id}:{window_id}:{event.outcome}:{event.side.value}"


def _coalesced_intent(
    events: list[TradeEvent],
    *,
    max_slippage_bps: int,
) -> tuple[ExecutionIntent, list[TradeEvent]] | None:
    if not events:
        return None
    ordered = sorted(events, key=lambda x: x.executed_ts)
    net = Decimal("0")
    for event in ordered:
        sign = Decimal("1") if event.side == Side.BUY else Decimal("-1")
        net += sign * event.notional_usd
    if net == 0:
        return None
    side = Side.BUY if net > 0 else Side.SELL
    first = ordered[0]
    return (
        ExecutionIntent(
            intent_id=f"{first.market_id}:{first.outcome}:{first.event_id}",
            market_id=first.market_id,
            outcome=first.outcome,
            side=side,
            target_notional_usd=abs(net),
            max_slippage_bps=max_slippage_bps,
            coalesced_event_ids=tuple(event.event_id for event in ordered),
            window_id=first.window.window_id if first.window else None,
        ),
        ordered,
    )


def _reconcile_settlements(
    *,
    pnl: PnLTracker,
    market_cache: MarketMetadataCache,
    log: logging.Logger,
) -> None:
    for market_id in pnl.open_markets():
        try:
            meta = market_cache.get(market_id)
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == 404:
                log.info("settlement_not_found market_id=%s", market_id)
            else:
                log.warning("settlement_fetch_error market_id=%s error=%s", market_id, exc)
            continue
        if not meta.closed:
            continue
        settled = pnl.settle_market(
            market_id=market_id,
            winning_outcome=meta.winning_outcome,
            outcome_settle_prices=meta.outcome_prices,
        )
        if settled > 0:
            log.info(
                "pnl_settlement_applied",
                extra={
                    "extra_fields": {
                        "market_id": market_id,
                        "winning_outcome": meta.winning_outcome,
                        "settled_positions": settled,
                    }
                },
            )


def _emit_snapshot(
    *,
    cfg: AppConfig,
    log: logging.Logger,
    metrics: MetricsCollector,
    alerts: AlertEvaluator,
    auto_kill: AutoKillGuard,
    kill_switch: KillSwitch,
    pnl: PnLTracker,
    market_cache: MarketMetadataCache,
    exporter: TelemetryExporter,
    final: bool = False,
) -> None:
    _reconcile_settlements(pnl=pnl, market_cache=market_cache, log=log)
    snapshot = metrics.snapshot()
    window_snapshot = metrics.snapshot_window()
    pnl_snapshot = pnl.snapshot()
    alert_state = alerts.evaluate(snapshot, ws_disconnect_s=0)
    if not cfg.execution.dry_run:
        auto_kill.evaluate(
            error_rate=window_snapshot.reject_rate,
            p95_latency_ms=int(
                window_snapshot.copy_delay_ms.p95 if window_snapshot.copy_delay_ms else 0
            ),
        )
    payload = {
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
        "realized_pnl_usd": str(pnl_snapshot.realized_trading_usd),
        "realized_settled_pnl_usd": str(pnl_snapshot.realized_settled_usd),
        "unrealized_pnl_usd": str(pnl_snapshot.unrealized_usd),
        "fees_usd": str(pnl_snapshot.fees_usd),
        "net_pnl_usd": str(pnl_snapshot.net_usd),
        "final_snapshot": final,
    }
    exporter.write_snapshot(payload)
    log.info("telemetry_snapshot", extra={"extra_fields": payload})


if __name__ == "__main__":
    main()
