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


class AutoKillGuard:
    def __init__(self, kill_switch: KillSwitch, thresholds: AutoKillThresholds) -> None:
        self._kill_switch = kill_switch
        self._thresholds = thresholds

    def evaluate(self, *, error_rate: float, p95_latency_ms: int) -> KillSwitchState:
        if error_rate > self._thresholds.max_error_rate:
            self._kill_switch.activate("auto_error_rate_threshold")
        if p95_latency_ms > self._thresholds.max_p95_latency_ms:
            self._kill_switch.activate("auto_latency_threshold")
        return self._kill_switch.check()
