from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class CopyConfig:
    source_wallet: str = "0x1d0034134e339a309700ff2d34e99fa2d48b0313"
    copy_mode: str = "intent_net"
    coalesce_ms: int = 300
    net_opposite_trades: bool = True


@dataclass(frozen=True)
class SizingConfig:
    mode: str = "capped_proportional"
    size_multiplier: float = 1.0
    min_order_notional_usd: float = 1.0
    max_notional_per_order_usd: float = 25.0
    max_notional_per_market_usd: float = 150.0
    max_total_notional_per_15m_window_usd: float = 400.0


@dataclass(frozen=True)
class ExecutionConfig:
    order_type: str = "marketable_limit"
    max_slippage_bps: int = 120
    near_expiry_cutoff_seconds: int = 25
    dry_run: bool = True


@dataclass(frozen=True)
class PolymarketConfig:
    clob_url: str = "https://clob.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/"
    private_key: str = ""
    funder: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""


@dataclass(frozen=True)
class AppConfig:
    copy: CopyConfig
    sizing: SizingConfig
    execution: ExecutionConfig
    polymarket: PolymarketConfig


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_config() -> AppConfig:
    load_dotenv()
    return AppConfig(
        copy=CopyConfig(
            source_wallet=os.getenv(
                "COPY_SOURCE_WALLET",
                CopyConfig.source_wallet,
            ),
            copy_mode=os.getenv("COPY_MODE", CopyConfig.copy_mode),
            coalesce_ms=int(os.getenv("COPY_COALESCE_MS", CopyConfig.coalesce_ms)),
            net_opposite_trades=_get_bool(
                "COPY_NET_OPPOSITE_TRADES",
                CopyConfig.net_opposite_trades,
            ),
        ),
        sizing=SizingConfig(
            mode=os.getenv("SIZING_MODE", SizingConfig.mode),
            size_multiplier=float(
                os.getenv("SIZING_SIZE_MULTIPLIER", SizingConfig.size_multiplier)
            ),
            min_order_notional_usd=float(
                os.getenv(
                    "SIZING_MIN_ORDER_NOTIONAL_USD",
                    SizingConfig.min_order_notional_usd,
                )
            ),
            max_notional_per_order_usd=float(
                os.getenv(
                    "SIZING_MAX_NOTIONAL_PER_ORDER_USD",
                    SizingConfig.max_notional_per_order_usd,
                )
            ),
            max_notional_per_market_usd=float(
                os.getenv(
                    "SIZING_MAX_NOTIONAL_PER_MARKET_USD",
                    SizingConfig.max_notional_per_market_usd,
                )
            ),
            max_total_notional_per_15m_window_usd=float(
                os.getenv(
                    "SIZING_MAX_TOTAL_NOTIONAL_PER_15M_WINDOW_USD",
                    SizingConfig.max_total_notional_per_15m_window_usd,
                )
            ),
        ),
        execution=ExecutionConfig(
            order_type=os.getenv("EXECUTION_ORDER_TYPE", ExecutionConfig.order_type),
            max_slippage_bps=int(
                os.getenv(
                    "EXECUTION_MAX_SLIPPAGE_BPS",
                    ExecutionConfig.max_slippage_bps,
                )
            ),
            near_expiry_cutoff_seconds=int(
                os.getenv(
                    "EXECUTION_NEAR_EXPIRY_CUTOFF_SECONDS",
                    ExecutionConfig.near_expiry_cutoff_seconds,
                )
            ),
            dry_run=_get_bool("EXECUTION_DRY_RUN", ExecutionConfig.dry_run),
        ),
        polymarket=PolymarketConfig(
            private_key=os.getenv("POLYMARKET_PRIVATE_KEY", ""),
            funder=os.getenv("POLYMARKET_FUNDER", ""),
            api_key=os.getenv("POLYMARKET_API_KEY", ""),
            api_secret=os.getenv("POLYMARKET_API_SECRET", ""),
            api_passphrase=os.getenv("POLYMARKET_API_PASSPHRASE", ""),
        ),
    )
