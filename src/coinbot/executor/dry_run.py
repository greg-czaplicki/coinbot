from __future__ import annotations

import logging
from dataclasses import dataclass

from coinbot.schemas import ExecutionIntent, RiskSnapshot


@dataclass(frozen=True)
class DryRunResult:
    sent: bool
    reason: str = ""


class DryRunExecutor:
    def __init__(self) -> None:
        self._log = logging.getLogger(self.__class__.__name__)

    def execute(
        self,
        *,
        intent: ExecutionIntent | None,
        risk: RiskSnapshot | None,
        correlation_id: str,
        blocked_reason: str = "",
    ) -> DryRunResult:
        if intent is None:
            reason = blocked_reason or (risk.blocked_reason if risk else "blocked")
            self._log.info(
                "dry_run_blocked",
                extra={
                    "extra_fields": {
                        "correlation_id": correlation_id,
                        "reason": reason,
                    }
                },
            )
            return DryRunResult(sent=False, reason=reason)

        self._log.info(
            "dry_run_intent",
            extra={
                "extra_fields": {
                    "correlation_id": correlation_id,
                    "intent_id": intent.intent_id,
                    "market_id": intent.market_id,
                    "outcome": intent.outcome,
                    "side": intent.side.value,
                    "target_notional_usd": str(intent.target_notional_usd),
                    "window_id": intent.window_id,
                    "risk_blocked": bool(risk and risk.blocked),
                    "risk_blocked_reason": risk.blocked_reason if risk else "",
                }
            },
        )
        return DryRunResult(sent=True)
