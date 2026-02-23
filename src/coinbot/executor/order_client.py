from __future__ import annotations

import hashlib
import importlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from coinbot.config import ExecutionConfig, PolymarketConfig
from coinbot.executor.market_cache import MarketMetadataCache
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
    error_code: str = ""


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
        market_cache: MarketMetadataCache | None = None,
        *,
        max_retries: int = 3,
        request_timeout_s: int = 3,
    ) -> None:
        self._polymarket = polymarket
        self._execution = execution
        self._market_cache = market_cache
        self._max_retries = max_retries
        self._request_timeout_s = request_timeout_s
        self._log = logging.getLogger(self.__class__.__name__)
        self._clob_client = None

    def submit_marketable_limit(
        self,
        *,
        intent: ExecutionIntent,
        price: Decimal,
        size: Decimal,
        market_slug: str | None = None,
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

        if self._market_cache is not None:
            live = self._submit_with_py_clob(
                intent=intent,
                market_slug=market_slug,
                price=price,
                size=size,
                client_order_id=client_order_id,
                endpoint=endpoint,
                payload=payload,
            )
            if live is not None:
                return live
            return OrderSubmission(
                client_order_id=client_order_id,
                endpoint=endpoint,
                payload=payload,
                accepted=False,
                status="rejected",
                error="token_id_missing",
                error_code="token_id_missing",
            )

        return self._post_with_retry(endpoint=endpoint, payload=payload, client_order_id=client_order_id)

    def _submit_with_py_clob(
        self,
        *,
        intent: ExecutionIntent,
        market_slug: str | None,
        price: Decimal,
        size: Decimal,
        client_order_id: str,
        endpoint: str,
        payload: dict,
    ) -> OrderSubmission | None:
        try:
            token_id, tick_size = self._resolve_order_target(intent=intent, market_slug=market_slug)
            if not token_id:
                self._log.warning("token_id_missing market=%s outcome=%s", market_slug or intent.market_id, intent.outcome)
                return None

            clob_types = importlib.import_module("py_clob_client.clob_types")
            order_builder = importlib.import_module("py_clob_client.client")
            ClobClient = getattr(order_builder, "ClobClient")
            OrderArgs = getattr(clob_types, "OrderArgs")
            OrderType = getattr(clob_types, "OrderType")

            client = self._get_or_create_clob_client(ClobClient, clob_types)
            price = _snap_price_to_tick(price=price, tick_size=tick_size)
            price, size = _sanitize_buy_amounts(price=price, size=size)
            payload["price"] = str(price)
            payload["size"] = str(size)
            order_args = OrderArgs(
                token_id=token_id,
                price=float(str(price)),
                size=float(str(size)),
                side=intent.side.value.upper(),
            )
            response = self._post_with_refresh(client, order_args, OrderType)
            return OrderSubmission(
                client_order_id=client_order_id,
                endpoint=endpoint,
                payload=payload,
                accepted=True,
                status="acknowledged",
                response=response if isinstance(response, dict) else {"response": str(response)},
            )
        except Exception as exc:
            # Retry with coarser precision ladders for markets that enforce strict amount scales.
            msg = str(exc).lower()
            if "invalid amounts" in msg:
                retries = _invalid_amounts_retries(price=price, size=size)
                for px2, sz2 in retries:
                    try:
                        payload["price"] = str(px2)
                        payload["size"] = str(sz2)
                        order_args2 = OrderArgs(
                            token_id=token_id,
                            price=float(str(px2)),
                            size=float(str(sz2)),
                            side=intent.side.value.upper(),
                        )
                        response = self._post_with_refresh(client, order_args2, OrderType)
                        return OrderSubmission(
                            client_order_id=client_order_id,
                            endpoint=endpoint,
                            payload=payload,
                            accepted=True,
                            status="acknowledged",
                            response=response if isinstance(response, dict) else {"response": str(response)},
                        )
                    except Exception as retry_exc:
                        exc = retry_exc
            error = str(exc)
            self._log.warning("py_clob_submit_error client_order_id=%s error=%s", client_order_id, exc)
            return OrderSubmission(
                client_order_id=client_order_id,
                endpoint=endpoint,
                payload=payload,
                accepted=False,
                status="rejected",
                error=error,
                error_code=_classify_error_code(error),
            )

    def _resolve_order_target(self, *, intent: ExecutionIntent, market_slug: str | None) -> tuple[str | None, Decimal]:
        tick = Decimal("0.01")
        if self._market_cache is None:
            return None, tick
        keys = [market_slug, intent.market_id]
        for key in keys:
            if not key:
                continue
            meta = self._market_cache.peek(key)
            if meta is None:
                continue
            try:
                tick = Decimal(str(meta.tick_size))
            except Exception:
                tick = Decimal("0.01")
            token_id = meta.outcomes.get(intent.outcome)
            if token_id:
                return token_id, tick
        # Avoid blocking submit path on metadata fetches. Warm cache asynchronously.
        for key in keys:
            if key:
                self._market_cache.request(key)
        return None, tick

    def _get_or_create_clob_client(self, ClobClient: object, clob_types: object):
        if self._clob_client is not None:
            return self._clob_client

        client = ClobClient(
            host=self._polymarket.clob_url,
            key=self._polymarket.private_key,
            chain_id=self._polymarket.chain_id,
            signature_type=self._polymarket.signature_type,
            funder=self._polymarket.funder,
        )
        if (
            self._polymarket.api_key
            and self._polymarket.api_secret
            and self._polymarket.api_passphrase
        ):
            creds_cls = getattr(clob_types, "ApiCreds", None)
            if creds_cls is not None:
                creds = creds_cls(
                    api_key=self._polymarket.api_key,
                    api_secret=self._polymarket.api_secret,
                    api_passphrase=self._polymarket.api_passphrase,
                )
                client.set_api_creds(creds)
            else:
                client.set_api_creds(
                    {
                        "key": self._polymarket.api_key,
                        "secret": self._polymarket.api_secret,
                        "passphrase": self._polymarket.api_passphrase,
                    }
                )
        else:
            # Derive credentials on first use if not provided.
            client.set_api_creds(client.create_or_derive_api_creds())
        self._clob_client = client
        return client

    def _post_with_refresh(self, client: object, order_args: object, OrderType: object):
        order_type = _resolve_marketable_limit_order_type(OrderType)
        signed = client.create_order(order_args)
        try:
            return client.post_order(signed, order_type)
        except Exception as exc:
            msg = str(exc).lower()
            if "invalid api key" not in msg and "unauthorized" not in msg:
                raise
            # Refresh/derive API creds once, then retry.
            client.set_api_creds(client.create_or_derive_api_creds())
            signed = client.create_order(order_args)
            return client.post_order(signed, order_type)

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
                    error = str(exc)
                    return OrderSubmission(
                        client_order_id=client_order_id,
                        endpoint=endpoint,
                        payload=payload,
                        accepted=False,
                        status="rejected",
                        error=error,
                        error_code=_classify_error_code(error),
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


def _sanitize_buy_amounts(*, price: Decimal, size: Decimal) -> tuple[Decimal, Decimal]:
    # CLOB constraints for market BUY: maker quote amount <= 2 dp, taker size <= 4 dp.
    if price <= 0:
        return price, size
    px = price.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    sz = size.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    notional = (px * sz).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if notional <= 0:
        return px, Decimal("0")
    sz = (notional / px).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return px, sz


def _snap_price_to_tick(*, price: Decimal, tick_size: Decimal) -> Decimal:
    if tick_size <= 0:
        return price
    steps = (price / tick_size).to_integral_value(rounding=ROUND_DOWN)
    snapped = steps * tick_size
    if snapped <= 0:
        return tick_size
    return snapped


def _invalid_amounts_retries(*, price: Decimal, size: Decimal) -> list[tuple[Decimal, Decimal]]:
    candidates = [
        (
            price.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
            size.quantize(Decimal("0.0001"), rounding=ROUND_DOWN),
        ),
        (
            price.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
            size.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        ),
        (
            price.quantize(Decimal("0.001"), rounding=ROUND_DOWN),
            size.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        ),
    ]
    out: list[tuple[Decimal, Decimal]] = []
    seen: set[str] = set()
    for px, sz in candidates:
        if px <= 0 or sz <= 0:
            continue
        key = f"{px}:{sz}"
        if key in seen:
            continue
        seen.add(key)
        out.append((px, sz))
    return out


def _classify_error_code(error: str) -> str:
    normalized = error.lower()
    if "token_id_missing" in normalized:
        return "token_id_missing"
    if "size" in normalized and "lower than the minimum" in normalized:
        return "min_size"
    return ""


def _resolve_marketable_limit_order_type(order_type_cls: object):
    # Marketable limit orders should prefer immediate execution semantics.
    for name in ("GTC", "IOC", "FOK"):
        value = getattr(order_type_cls, name, None)
        if value is not None:
            return value
    raise ValueError("OrderType missing FOK/IOC/GTC attributes")


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
