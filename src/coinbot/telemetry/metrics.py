from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass
class StageTimes:
    event_receive_ts_ms: int | None = None
    decision_ts_ms: int | None = None
    order_submit_ts_ms: int | None = None
    ack_ts_ms: int | None = None


@dataclass(frozen=True)
class PercentileSummary:
    p50: float
    p95: float
    p99: float


@dataclass(frozen=True)
class DashboardSnapshot:
    copy_delay_ms: PercentileSummary | None
    decision_delay_ms: PercentileSummary | None
    submit_to_ack_ms: PercentileSummary | None
    source_fills: int
    destination_orders: int
    coalescing_efficiency: float | None
    reject_rate: float


class MetricsCollector:
    def __init__(self) -> None:
        self._by_correlation: dict[str, StageTimes] = {}
        self._copy_delays: list[float] = []
        self._decision_delays: list[float] = []
        self._submit_to_ack_delays: list[float] = []
        self._source_fills = 0
        self._destination_orders = 0
        self._submissions = 0
        self._rejections = 0

    def record_event_receive(self, correlation_id: str, ts_ms: int) -> None:
        self._stage(correlation_id).event_receive_ts_ms = ts_ms
        self._source_fills += 1

    def record_decision(self, correlation_id: str, ts_ms: int) -> None:
        stage = self._stage(correlation_id)
        stage.decision_ts_ms = ts_ms
        if stage.event_receive_ts_ms is not None:
            self._decision_delays.append(ts_ms - stage.event_receive_ts_ms)

    def record_order_submit(self, correlation_id: str, ts_ms: int) -> None:
        stage = self._stage(correlation_id)
        stage.order_submit_ts_ms = ts_ms
        self._destination_orders += 1
        self._submissions += 1
        if stage.event_receive_ts_ms is not None:
            self._copy_delays.append(ts_ms - stage.event_receive_ts_ms)

    def record_ack(self, correlation_id: str, ts_ms: int, *, accepted: bool) -> None:
        stage = self._stage(correlation_id)
        stage.ack_ts_ms = ts_ms
        if stage.order_submit_ts_ms is not None:
            self._submit_to_ack_delays.append(ts_ms - stage.order_submit_ts_ms)
        if not accepted:
            self._rejections += 1

    def snapshot(self) -> DashboardSnapshot:
        return DashboardSnapshot(
            copy_delay_ms=_summary(self._copy_delays),
            decision_delay_ms=_summary(self._decision_delays),
            submit_to_ack_ms=_summary(self._submit_to_ack_delays),
            source_fills=self._source_fills,
            destination_orders=self._destination_orders,
            coalescing_efficiency=self._coalescing_efficiency(),
            reject_rate=(self._rejections / self._submissions) if self._submissions else 0.0,
        )

    def _stage(self, correlation_id: str) -> StageTimes:
        if correlation_id not in self._by_correlation:
            self._by_correlation[correlation_id] = StageTimes()
        return self._by_correlation[correlation_id]

    def _coalescing_efficiency(self) -> float | None:
        if self._destination_orders == 0:
            return None
        return self._source_fills / self._destination_orders


def _summary(values: list[float]) -> PercentileSummary | None:
    if not values:
        return None
    ordered = sorted(values)
    return PercentileSummary(
        p50=median(ordered),
        p95=_percentile(ordered, 95),
        p99=_percentile(ordered, 99),
    )


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = int(round((p / 100) * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]
