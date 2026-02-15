from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KillSwitchState:
    active: bool = False
    reason: str = ""


class KillSwitch:
    def __init__(self) -> None:
        self._state = KillSwitchState()

    def activate(self, reason: str) -> None:
        self._state.active = True
        self._state.reason = reason

    def deactivate(self) -> None:
        self._state.active = False
        self._state.reason = ""

    def check(self) -> KillSwitchState:
        return KillSwitchState(active=self._state.active, reason=self._state.reason)


@dataclass(frozen=True)
class AutoKillThresholds:
    max_error_rate: float = 0.2
    max_p95_latency_ms: int = 1200
    recover_max_error_rate: float = 0.1
    recover_max_p95_latency_ms: int = 800
    recovery_consecutive_snapshots: int = 2


class AutoKillGuard:
    def __init__(self, kill_switch: KillSwitch, thresholds: AutoKillThresholds) -> None:
        self._kill_switch = kill_switch
        self._thresholds = thresholds
        self._healthy_streak = 0

    def evaluate(self, *, error_rate: float, p95_latency_ms: int) -> KillSwitchState:
        if error_rate > self._thresholds.max_error_rate:
            self._kill_switch.activate("auto_error_rate_threshold")
            self._healthy_streak = 0
            return self._kill_switch.check()
        if p95_latency_ms > self._thresholds.max_p95_latency_ms:
            self._kill_switch.activate("auto_latency_threshold")
            self._healthy_streak = 0
            return self._kill_switch.check()

        # Auto-recover from an active kill switch after sustained healthy telemetry.
        if self._kill_switch.check().active:
            healthy = (
                error_rate <= self._thresholds.recover_max_error_rate
                and p95_latency_ms <= self._thresholds.recover_max_p95_latency_ms
            )
            if healthy:
                self._healthy_streak += 1
                if self._healthy_streak >= self._thresholds.recovery_consecutive_snapshots:
                    self._kill_switch.deactivate()
                    self._healthy_streak = 0
            else:
                self._healthy_streak = 0
        return self._kill_switch.check()
