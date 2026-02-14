from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    def load_dotenv() -> None:
        return None


@dataclass(frozen=True)
class CopyConfig:
    source_wallet: str = "0x1d0034134e339a309700ff2d34e99fa2d48b0313"
    copy_mode: str = "intent_net"
    coalesce_ms: int = 300
    net_opposite_trades: bool = True


@dataclass(frozen=True)
class SizingConfig:
    mode: str = "capped_proportional"
    fixed_order_notional_usd: float = 10.0
    size_multiplier: float = 1.0
    min_order_notional_usd: float = 1.0
    max_notional_per_order_usd: float = 25.0
    max_notional_per_market_usd: float = 150.0
    max_daily_traded_volume_usd: float = 1500.0
    max_total_notional_per_15m_window_usd: float = 400.0


@dataclass(frozen=True)
class ExecutionConfig:
    order_type: str = "marketable_limit"
    max_slippage_bps: int = 120
    near_expiry_cutoff_seconds: int = 25
    fee_bps: float = 0.0
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
    cfg = AppConfig(
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
            fixed_order_notional_usd=float(
                os.getenv(
                    "SIZING_FIXED_ORDER_NOTIONAL_USD",
                    SizingConfig.fixed_order_notional_usd,
                )
            ),
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
            max_daily_traded_volume_usd=float(
                os.getenv(
                    "SIZING_MAX_DAILY_TRADED_VOLUME_USD",
                    SizingConfig.max_daily_traded_volume_usd,
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
            fee_bps=float(
                os.getenv(
                    "EXECUTION_FEE_BPS",
                    ExecutionConfig.fee_bps,
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
    validate_config(cfg)
    return cfg


def validate_config(cfg: AppConfig) -> None:
    if not cfg.copy.source_wallet.startswith("0x") or len(cfg.copy.source_wallet) != 42:
        raise ValueError("COPY_SOURCE_WALLET must be a 42-char 0x address")
    if cfg.copy.copy_mode not in {"intent_net", "fill_by_fill"}:
        raise ValueError("COPY_MODE must be one of: intent_net, fill_by_fill")
    if cfg.copy.coalesce_ms <= 0:
        raise ValueError("COPY_COALESCE_MS must be > 0")
    if cfg.sizing.mode not in {"fixed", "proportional", "capped_proportional"}:
        raise ValueError("SIZING_MODE must be fixed|proportional|capped_proportional")
    if cfg.sizing.fixed_order_notional_usd <= 0:
        raise ValueError("SIZING_FIXED_ORDER_NOTIONAL_USD must be > 0")
    if cfg.sizing.size_multiplier <= 0:
        raise ValueError("SIZING_SIZE_MULTIPLIER must be > 0")
    if cfg.sizing.min_order_notional_usd <= 0:
        raise ValueError("SIZING_MIN_ORDER_NOTIONAL_USD must be > 0")
    if cfg.sizing.max_notional_per_order_usd < cfg.sizing.min_order_notional_usd:
        raise ValueError("SIZING_MAX_NOTIONAL_PER_ORDER_USD must be >= min order notional")
    if cfg.sizing.max_notional_per_market_usd <= 0:
        raise ValueError("SIZING_MAX_NOTIONAL_PER_MARKET_USD must be > 0")
    if cfg.sizing.max_daily_traded_volume_usd <= 0:
        raise ValueError("SIZING_MAX_DAILY_TRADED_VOLUME_USD must be > 0")
    if cfg.sizing.max_total_notional_per_15m_window_usd <= 0:
        raise ValueError("SIZING_MAX_TOTAL_NOTIONAL_PER_15M_WINDOW_USD must be > 0")
    if cfg.execution.order_type != "marketable_limit":
        raise ValueError("EXECUTION_ORDER_TYPE must be marketable_limit in v1")
    if cfg.execution.max_slippage_bps <= 0:
        raise ValueError("EXECUTION_MAX_SLIPPAGE_BPS must be > 0")
    if cfg.execution.near_expiry_cutoff_seconds < 0:
        raise ValueError("EXECUTION_NEAR_EXPIRY_CUTOFF_SECONDS must be >= 0")
    if cfg.execution.fee_bps < 0:
        raise ValueError("EXECUTION_FEE_BPS must be >= 0")
    if not cfg.execution.dry_run:
        missing = []
        if not cfg.polymarket.private_key:
            missing.append("POLYMARKET_PRIVATE_KEY")
        if not cfg.polymarket.funder:
            missing.append("POLYMARKET_FUNDER")
        if not cfg.polymarket.api_key:
            missing.append("POLYMARKET_API_KEY")
        if not cfg.polymarket.api_secret:
            missing.append("POLYMARKET_API_SECRET")
        if not cfg.polymarket.api_passphrase:
            missing.append("POLYMARKET_API_PASSPHRASE")
        if missing:
            joined = ",".join(missing)
            raise ValueError(f"Missing required Polymarket credentials in live mode: {joined}")
