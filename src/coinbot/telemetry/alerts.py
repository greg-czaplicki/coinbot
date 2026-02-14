from __future__ import annotations

from dataclasses import dataclass

from coinbot.telemetry.metrics import DashboardSnapshot


@dataclass(frozen=True)
class AlertThresholds:
    p95_copy_delay_ms: int = 800
    max_reject_rate: float = 0.1
    max_ws_disconnect_s: int = 20


@dataclass(frozen=True)
class AlertState:
    websocket_disconnect_breach: bool
    reject_spike_breach: bool
    p95_latency_breach: bool


class AlertEvaluator:
    def __init__(self, thresholds: AlertThresholds) -> None:
        self._thresholds = thresholds

    def evaluate(self, snapshot: DashboardSnapshot, *, ws_disconnect_s: int) -> AlertState:
        p95 = snapshot.copy_delay_ms.p95 if snapshot.copy_delay_ms else 0
        return AlertState(
            websocket_disconnect_breach=ws_disconnect_s > self._thresholds.max_ws_disconnect_s,
            reject_spike_breach=snapshot.reject_rate > self._thresholds.max_reject_rate,
            p95_latency_breach=p95 > self._thresholds.p95_copy_delay_ms,
        )
