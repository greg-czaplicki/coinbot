from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from coinbot.config import ExecutionConfig, PolymarketConfig
from coinbot.schemas import ExecutionIntent


@dataclass(frozen=True)
class OrderSubmission:
    client_order_id: str
    endpoint: str
    payload: dict
    accepted: bool
    status: str
    response: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class OrderLifecycle:
    client_order_id: str
    status: str = "created"
    filled_notional_usd: Decimal = Decimal("0")
    update_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OrderLifecycleStore:
    def __init__(self) -> None:
        self._orders: dict[str, OrderLifecycle] = {}

    def register(self, submission: OrderSubmission) -> OrderLifecycle:
        lifecycle = OrderLifecycle(
            client_order_id=submission.client_order_id,
            status="acknowledged" if submission.accepted else "rejected",
        )
        self._orders[submission.client_order_id] = lifecycle
        return lifecycle

    def mark_partial_fill(self, client_order_id: str, filled_notional_usd: Decimal) -> None:
        lifecycle = self._orders[client_order_id]
        lifecycle.status = "partial_fill"
        lifecycle.filled_notional_usd += filled_notional_usd
        lifecycle.update_ts = datetime.now(timezone.utc)

    def mark_filled(self, client_order_id: str, filled_notional_usd: Decimal) -> None:
        lifecycle = self._orders[client_order_id]
        lifecycle.status = "filled"
        lifecycle.filled_notional_usd = filled_notional_usd
        lifecycle.update_ts = datetime.now(timezone.utc)


class ClobOrderClient:
    def __init__(
        self,
        polymarket: PolymarketConfig,
        execution: ExecutionConfig,
        *,
        max_retries: int = 3,
        request_timeout_s: int = 3,
    ) -> None:
        self._polymarket = polymarket
        self._execution = execution
        self._max_retries = max_retries
        self._request_timeout_s = request_timeout_s
        self._log = logging.getLogger(self.__class__.__name__)

    def submit_marketable_limit(
        self,
        *,
        intent: ExecutionIntent,
        price: Decimal,
        size: Decimal,
    ) -> OrderSubmission:
        if self._execution.order_type != "marketable_limit":
            raise ValueError(f"Unsupported order type: {self._execution.order_type}")

        client_order_id = deterministic_client_order_id(intent)
        payload = {
            "client_order_id": client_order_id,
            "market_id": intent.market_id,
            "outcome": intent.outcome,
            "side": intent.side.value,
            "price": str(price),
            "size": str(size),
            "order_type": "marketable_limit",
            "max_slippage_bps": intent.max_slippage_bps,
        }

        endpoint = f"{self._polymarket.clob_url}/order"
        if self._execution.dry_run:
            return OrderSubmission(
                client_order_id=client_order_id,
                endpoint=endpoint,
                payload=payload,
                accepted=True,
                status="dry_run_acknowledged",
                response={"dry_run": True},
            )

        return self._post_with_retry(endpoint=endpoint, payload=payload, client_order_id=client_order_id)

    def _post_with_retry(self, *, endpoint: str, payload: dict, client_order_id: str) -> OrderSubmission:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "POLY_API_KEY": self._polymarket.api_key,
            "POLY_API_SECRET": self._polymarket.api_secret,
            "POLY_PASSPHRASE": self._polymarket.api_passphrase,
        }

        for attempt in range(1, self._max_retries + 1):
            try:
                req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self._request_timeout_s) as resp:
                    response = json.loads(resp.read().decode("utf-8"))
                return OrderSubmission(
                    client_order_id=client_order_id,
                    endpoint=endpoint,
                    payload=payload,
                    accepted=True,
                    status="acknowledged",
                    response=response,
                )
            except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                self._log.warning(
                    "order_submit_retry client_order_id=%s attempt=%s error=%s",
                    client_order_id,
                    attempt,
                    exc,
                )
                if attempt == self._max_retries:
                    return OrderSubmission(
                        client_order_id=client_order_id,
                        endpoint=endpoint,
                        payload=payload,
                        accepted=False,
                        status="rejected",
                        error=str(exc),
                    )
                time.sleep(0.1 * attempt)

        return OrderSubmission(
            client_order_id=client_order_id,
            endpoint=endpoint,
            payload=payload,
            accepted=False,
            status="rejected",
            error="unreachable",
        )


def deterministic_client_order_id(intent: ExecutionIntent) -> str:
    digest_input = "|".join(
        [
            intent.market_id,
            intent.outcome,
            intent.side.value,
            intent.window_id or "na",
            ",".join(intent.coalesced_event_ids),
            str(intent.target_notional_usd),
        ]
    )
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return f"cb-{digest[:24]}"
