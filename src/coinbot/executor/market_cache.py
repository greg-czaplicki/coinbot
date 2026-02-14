from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from coinbot.config import PolymarketConfig


@dataclass(frozen=True)
class MarketMetadata:
    market_id: str
    active: bool
    closed: bool
    tick_size: str
    outcomes: dict[str, str]
    winning_outcome: str | None
    outcome_prices: dict[str, Decimal]


class MarketMetadataCache:
    def __init__(self, polymarket: PolymarketConfig, *, ttl_s: int = 60) -> None:
        self._polymarket = polymarket
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[float, MarketMetadata]] = {}

    def get(self, market_id: str) -> MarketMetadata:
        now = time.time()
        cached = self._cache.get(market_id)
        if cached and now - cached[0] < self._ttl_s:
            return cached[1]
        meta = self._fetch(market_id)
        self._cache[market_id] = (now, meta)
        return meta

    def _fetch(self, market_id: str) -> MarketMetadata:
        # Gamma has rich market metadata used to map outcome labels to token IDs.
        urls = [
            f"{self._polymarket.gamma_api_url}/markets?{urllib.parse.urlencode({'id': market_id})}",
            f"{self._polymarket.gamma_api_url}/api/markets?{urllib.parse.urlencode({'id': market_id})}",
            f"{self._polymarket.gamma_api_url}/markets?{urllib.parse.urlencode({'slug': market_id})}",
            f"{self._polymarket.gamma_api_url}/api/markets?{urllib.parse.urlencode({'slug': market_id})}",
        ]
        headers = {
            "Accept": "application/json",
            "User-Agent": "coinbot/0.1 (+https://github.com/greg-czaplicki/coinbot)",
            "Connection": "keep-alive",
        }
        payload: Any = {}
        last_error: Exception | None = None
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=4) as resp:
                    candidate = json.loads(resp.read().decode("utf-8"))
                item = _first_item(candidate)
                if _looks_like_market(item):
                    payload = candidate
                    last_error = None
                    break
            except Exception as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error

        item = _first_item(payload)
        outcomes: dict[str, str] = {}
        labels = _extract_outcome_labels(item.get("outcomes", []) or [])
        token_ids = _extract_token_ids(item)
        if labels and token_ids and len(labels) == len(token_ids):
            outcomes = {labels[i]: token_ids[i] for i in range(len(labels))}
        else:
            for raw in item.get("outcomes", []) or []:
                if isinstance(raw, dict):
                    label = str(raw.get("name") or raw.get("outcome") or "")
                    token_id = str(raw.get("tokenId") or raw.get("token_id") or "")
                    if label and token_id:
                        outcomes[label] = token_id

        outcome_prices = _extract_outcome_prices(item)
        winning_outcome = _extract_winning_outcome(item, outcome_prices)

        return MarketMetadata(
            market_id=market_id,
            active=bool(item.get("active", True)),
            closed=bool(item.get("closed", False)),
            tick_size=str(item.get("minimumTickSize") or item.get("tickSize") or "0.01"),
            outcomes=outcomes,
            winning_outcome=winning_outcome,
            outcome_prices=outcome_prices,
        )


def _first_item(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload:
        return payload[0] if isinstance(payload[0], dict) else {}
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list) and payload["data"]:
            first = payload["data"][0]
            return first if isinstance(first, dict) else {}
        return payload
    return {}


def _looks_like_market(item: dict[str, Any]) -> bool:
    if not item:
        return False
    return bool(
        item.get("conditionId")
        or item.get("slug")
        or item.get("outcomes")
        or item.get("outcomePrices")
    )


def _extract_outcome_prices(item: dict[str, Any]) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    raw_outcomes = item.get("outcomes", []) or []
    labels = _extract_outcome_labels(raw_outcomes)

    raw_prices = item.get("outcomePrices")
    values: list[Any] = []
    if isinstance(raw_prices, str):
        try:
            parsed = json.loads(raw_prices)
            if isinstance(parsed, list):
                values = parsed
        except json.JSONDecodeError:
            values = []
    elif isinstance(raw_prices, list):
        values = raw_prices

    for idx, value in enumerate(values):
        if idx >= len(labels) or not labels[idx]:
            continue
        px = _to_decimal(value)
        if px is not None:
            prices[labels[idx]] = px
    return prices


def _extract_winning_outcome(item: dict[str, Any], outcome_prices: dict[str, Decimal]) -> str | None:
    for key in ["winningOutcome", "resolvedOutcome", "winner", "winnerOutcome", "result"]:
        raw = item.get(key)
        if isinstance(raw, str) and raw:
            return raw

    if outcome_prices:
        # If a market is resolved and exactly one outcome is priced at 1, treat that as winner.
        one_outcomes = [k for k, v in outcome_prices.items() if v == Decimal("1")]
        if len(one_outcomes) == 1:
            return one_outcomes[0]
    return None


def _to_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _extract_outcome_labels(raw_outcomes: Any) -> list[str]:
    labels: list[str] = []
    if isinstance(raw_outcomes, str):
        try:
            parsed_outcomes = json.loads(raw_outcomes)
            if isinstance(parsed_outcomes, list):
                raw_outcomes = parsed_outcomes
        except json.JSONDecodeError:
            raw_outcomes = []
    if isinstance(raw_outcomes, list):
        for raw in raw_outcomes:
            if isinstance(raw, dict):
                labels.append(str(raw.get("name") or raw.get("outcome") or ""))
            elif isinstance(raw, str):
                labels.append(raw)
    return [l for l in labels if l]


def _extract_token_ids(item: dict[str, Any]) -> list[str]:
    raw_ids = item.get("clobTokenIds", []) or item.get("tokenIds", [])
    if isinstance(raw_ids, str):
        try:
            parsed = json.loads(raw_ids)
            if isinstance(parsed, list):
                raw_ids = parsed
        except json.JSONDecodeError:
            raw_ids = []
    if not isinstance(raw_ids, list):
        return []
    return [str(x) for x in raw_ids if str(x)]
