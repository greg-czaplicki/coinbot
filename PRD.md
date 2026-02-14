# Polymarket Copy-Trading Bot PRD

## 1. Objective
Build a bot that mirrors trades from one source wallet on Polymarket with minimal delay and controlled risk.

Primary success criterion:
- Median copy delay (source fill event to our order submission): <= 300 ms
- P95 copy delay: <= 800 ms

## 2. Scope

In scope:
- Monitor a specific source wallet in real time.
- Infer source position changes from fills/transfers/events.
- Replicate buys/sells using configurable sizing rules.
- Risk controls (max size, max exposure per market, circuit breaker).
- Observability (latency metrics, logs, alerts).
- Run continuously on a Netherlands VPS.

Out of scope (v1):
- Multi-wallet copying
- Strategy optimization / alpha signals
- GUI dashboard (CLI + logs only)

## 3. Key Constraints & Assumptions
- Latency matters most, but end-to-end delay is dominated by:
  - How fast source wallet activity is detected
  - Market/orderbook/API path
  - Network path and exchange response
- Polymarket integration details and auth flows are stable enough for API usage.
- VPS has stable low-jitter network and NTP sync.
- Source wallet to mirror (v1): `0x1d0034134e339a309700ff2d34e99fa2d48b0313`
- Observed behavior: many small buys in short bursts on 15-minute crypto "Up or Down" markets.

## 4. Users
- Operator (you): configures wallet, risk limits, and deployment.

## 5. Functional Requirements
1. Wallet tracking
- Subscribe to real-time events relevant to source wallet.
- Deduplicate events and handle reorg/replay safety.

2. Trade replication
- Map source action -> destination action (buy/sell/size).
- Support sizing modes:
  - Fixed amount per copied trade
  - Proportional to source notional
  - Capped proportional (recommended)
- Support burst handling:
  - Coalesce multiple source fills in same market/outcome over a short window (e.g. 150-400 ms) into one execution intent.
  - Preserve direction and net size while reducing order spam and reject risk.

3. Execution engine
- Place orders quickly with configurable aggression:
  - `marketable_limit` (recommended)
  - passive limit (optional later)
- Retry on transient failures with strict idempotency.
- Track market window timing:
  - Avoid opening new copy positions close to market resolution cutoff (configurable guard, e.g. last 20-30s).

4. Risk and safety
- Hard caps:
  - Max order size
  - Max daily volume
  - Max market exposure
- Kill switch:
  - Manual stop command
  - Auto-stop on error-rate/latency threshold breach

5. Ops and monitoring
- Structured logs for each stage:
  - Event receive -> decision -> submit -> ack/fill
- Metrics:
  - Copy delay histogram (p50/p95/p99)
  - Success/failure rate
  - Slippage vs source
- Alerting for downtime, auth failures, repeated rejects.

## 6. Non-Functional Requirements
- Reliability: recover from websocket disconnects and restarts without duplicate orders.
- Performance: sustain bursts of source activity.
- Security:
  - Private keys in env/secret store only
  - Principle of least privilege
  - No secrets in logs

## 7. Architecture (v1)
Components:
1. `watcher`
- Subscribes to source wallet events.
- Emits normalized trade events.

2. `decision-engine`
- Applies sizing + risk checks.
- Produces executable intents.

3. `executor`
- Places/cancels orders.
- Tracks acknowledgements/fills/retries.

4. `state-store`
- Minimal durable state (sqlite or postgres):
  - processed event IDs
  - open intents/orders
  - exposures and PnL snapshot

5. `telemetry`
- Metrics endpoint + logs + alert hooks.

Suggested data flow:
- wallet event -> normalize -> dedupe -> risk check -> place order -> confirm -> record metrics

## 8. Latency Strategy
1. Source detection
- Prefer websocket/subscription feeds over polling.
- Maintain warm connections and heartbeat watchdog.

2. Networking
- Keep VPS in Netherlands as requested; benchmark RTT to Polymarket endpoints.
- Tune TCP/socket settings; avoid reconnect churn.

3. Execution path
- Precompute market metadata in memory.
- Avoid blocking I/O in hot path.
- Use idempotency keys and bounded retries.
- Add micro-batching/coalescing for burst fills to improve queue stability and tail latency.

4. Measurement first
- Instrument stage-level timers before optimization.
- Set SLO alerts on p95 copy delay.

## 9. Rust vs Python Decision
Short answer:
- Start with Python for fastest validation.
- Move hot path to Rust if measured p95/p99 latency or CPU jitter is unacceptable.

Why:
- In this system, language is usually not the largest latency contributor at first.
- Python can hit good performance with async I/O and websocket feeds.
- Rust gives tighter tail latency, better concurrency safety, and lower runtime jitter when scaling.

Recommended path:
1. MVP in Python (`asyncio`, websocket client, strict profiling).
2. Benchmark for 1-2 weeks live/paper.
3. If p95/p99 misses target, rewrite watcher+executor in Rust and keep control plane in Python or move fully to Rust.

## 10. Acceptance Criteria (v1)
- Bot runs 7 days with automatic reconnect and no duplicate executions.
- >= 98% of eligible source trades are copied.
- Median copy delay <= 300 ms; p95 <= 800 ms in production conditions.
- Risk limits prevent any breach during test scenarios.
- For burst scenarios (>=5 source fills in 2s on same market/outcome), bot emits <=2 destination orders while matching net intended size within configured tolerance.

## 11. Replication Policy (v1 Default)
Goal:
- Copy intent-level exposure for short-window crypto markets, not raw 1:1 micro-fills.

Default policy:
- `copy_mode`: `intent_net`
- `source_wallet`: `0x1d0034134e339a309700ff2d34e99fa2d48b0313`
- `coalesce_ms`: `300`
- `net_opposite_trades`: `true`
- `sizing_mode`: `capped_proportional`
- `size_multiplier`: `1.00` (tunable)
- `max_notional_per_order_usd`: `25`
- `max_notional_per_market_usd`: `150`
- `max_total_notional_per_15m_window_usd`: `400`
- `near_expiry_cutoff_seconds`: `25`
- `min_order_notional_usd`: `1`
- `max_slippage_bps`: `120`
- `dry_run`: `true` for first rollout

Operational semantics:
- Aggregate source fills by `(market_id, outcome)` in the coalesce window.
- If opposite fills happen in the same market window, net before execution when `net_opposite_trades=true`.
- Ignore new opening intents within `near_expiry_cutoff_seconds` of market end.
- Drop tiny intents below `min_order_notional_usd` to reduce noise/rejects.
- Apply portfolio/window caps before per-order submit.

Example config shape:
```yaml
copy:
  source_wallet: "0x1d0034134e339a309700ff2d34e99fa2d48b0313"
  copy_mode: "intent_net"   # intent_net | fill_by_fill
  coalesce_ms: 300
  net_opposite_trades: true

sizing:
  mode: "capped_proportional"  # fixed | proportional | capped_proportional
  size_multiplier: 1.0
  min_order_notional_usd: 1
  max_notional_per_order_usd: 25
  max_notional_per_market_usd: 150
  max_total_notional_per_15m_window_usd: 400

execution:
  order_type: "marketable_limit"
  max_slippage_bps: 120
  near_expiry_cutoff_seconds: 25
  dry_run: true
```

## 12. Open Questions
- Exact source signal: on-chain events, Polymarket user-trade feed, or both?
- Preferred order type behavior under low liquidity?
- Regulatory/compliance constraints for your jurisdiction and venue terms?
- Max capital allocation and exposure constraints?
- Should opposing source trades inside same 15-minute market be netted (recommended) or mirrored as separate orders?
