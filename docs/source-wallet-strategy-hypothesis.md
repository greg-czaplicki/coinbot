# Source Wallet Strategy Hypothesis

This is a working hypothesis for wallet `0x1d0034134e339a309700ff2d34e99fa2d48b0313` based on observed fills and bot telemetry.

## What It Looks Like They Are Doing

1. Trading very short-duration momentum/reversion markets.
- Repeated activity in `*-updown-5m` and `*-updown-15m` contracts.
- Most active symbols seen: BTC, ETH, XRP.

2. Running high-frequency, small-to-medium notional clips.
- Frequent event stream with many source fills.
- Individual candidate notionals often in low single/double digits.

3. Leaning on fast entries, not deep hold time.
- A lot of activity is close to expiry windows.
- `near_expiry_cutoff` blocks imply source entries can be very late in the window.

4. Spreading opportunity across multiple markets/windows.
- Simultaneous opportunities across symbols and rolling windows.
- Your bot often blocks by `window_cap_exceeded` and `market_cap_exceeded`, suggesting source wallet keeps deploying flow while your caps are intentionally tight.

## Likely Edge (Hypothesis)

Primary hypothesis:
- Microstructure timing edge in short-horizon contracts (fast reaction to directional flow/news bursts), monetized via many small entries rather than large directional conviction per trade.

Secondary hypothesis:
- Basket-style flow harvesting across BTC/ETH/XRP windows, where expectancy comes from aggregate hit rate and timing, not from any single large position.

## Why Your Copy Bot Misses Part of It

1. Conservative risk caps truncate throughput.
- You are often blocked by window/market caps before source flow completes.

2. Minimum order filter removes tail trades.
- `below_min_order_notional` means some source signals are filtered out.

3. Late-window entries are intentionally skipped.
- `near_expiry_cutoff` protects execution quality but can miss source wallet's late timing trades.

## How To Validate This Hypothesis

1. Add outcome attribution by block reason.
- Compare expected PnL of blocked vs executed intents by reason (`window_cap_exceeded`, `market_cap_exceeded`, `below_min_order_notional`, `near_expiry_cutoff`).

2. Track source-to-copy timing by market window.
- Bucket by time-to-expiry when source fills occur.

3. Run A/B config windows.
- Session A: current conservative caps.
- Session B: slightly looser caps (same bankroll guardrails).
- Compare net PnL, reject rate, drawdown, and fill count.

4. Measure symbol/window contribution.
- Break PnL out by market family (BTC/ETH/XRP) and tenor (5m vs 15m).

## Practical Interpretation

The source wallet appears to be a fast-flow short-window trader. Your current setup already captures the pattern safely, but throttles it heavily. If this hypothesis is correct, performance improvement will come from selective throughput increases (window/market caps and min-notional tuning), not from changing the core copy logic.
