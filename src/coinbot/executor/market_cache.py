from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from coinbot.config import PolymarketConfig


@dataclass(frozen=True)
class MarketMetadata:
    market_id: str
    active: bool
    closed: bool
    tick_size: str
    outcomes: dict[str, str]


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
        query = urllib.parse.urlencode({"id": market_id})
        url = f"{self._polymarket.gamma_api_url}/markets?{query}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        item = _first_item(payload)
        outcomes: dict[str, str] = {}
        for raw in item.get("outcomes", []) or []:
            if isinstance(raw, dict):
                label = str(raw.get("name") or raw.get("outcome") or "")
                token_id = str(raw.get("tokenId") or raw.get("token_id") or "")
                if label and token_id:
                    outcomes[label] = token_id

        return MarketMetadata(
            market_id=market_id,
            active=bool(item.get("active", True)),
            closed=bool(item.get("closed", False)),
            tick_size=str(item.get("minimumTickSize") or item.get("tickSize") or "0.01"),
            outcomes=outcomes,
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
