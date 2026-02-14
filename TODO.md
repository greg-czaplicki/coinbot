# Build TODO (Latency-First)

## Phase 0: Foundation
- [x] Confirm Polymarket API/auth/event interfaces to use for source wallet tracking.
- [x] Decide runtime for MVP: Python async stack (recommended first).
- [x] Create `.env.example` with required secrets and config keys.
- [x] Set source wallet config default to `0x1d0034134e339a309700ff2d34e99fa2d48b0313`.
- [x] Add replication config keys and defaults:
  - [x] `copy_mode=intent_net`
  - [x] `coalesce_ms=300`
  - [x] `net_opposite_trades=true`
  - [x] `near_expiry_cutoff_seconds=25`
  - [x] `max_notional_per_order_usd=25`
  - [x] `max_notional_per_market_usd=150`
  - [x] `max_total_notional_per_15m_window_usd=400`
- [x] Set up project skeleton:
  - [x] `src/watcher`
  - [x] `src/decision_engine`
  - [x] `src/executor`
  - [x] `src/state_store`
  - [x] `src/telemetry`
- [x] Add structured logging and request/event correlation IDs.

Exit criteria:
- Local service boots and all modules initialize with health checks.

## Phase 1: Source Wallet Event Ingestion
- [x] Implement websocket subscription(s) for source wallet activity.
- [x] Normalize incoming events into internal `TradeEvent` schema.
- [x] Include market window metadata in normalized events (asset, start/end, outcome side).
- [x] Add deduplication by event ID + tx hash + sequence rules.
- [x] Persist last processed offsets/checkpoints.
- [x] Implement reconnect logic with exponential backoff and replay safety.

Exit criteria:
- In paper mode, all source wallet trades are captured and normalized without duplicates for 48h.

## Phase 2: Decision + Risk Engine
- [x] Implement sizing modes:
  - [x] Fixed size
  - [x] Proportional
  - [x] Capped proportional (default)
- [x] Add hard risk checks:
  - [x] Max order notional
  - [x] Max market exposure
  - [x] Max daily traded volume
- [x] Implement burst coalescing (same market + same outcome + short window) before execution.
- [x] Add near-expiry guard (do not open new copied positions in final N seconds of 15m market).
- [x] Add optional netting mode for rapid opposite trades in same market window.
- [x] Add intent-net aggregator keyed by `(market_id, outcome, window_id)`.
- [x] Drop intents below `min_order_notional_usd`.
- [x] Enforce `max_total_notional_per_15m_window_usd` cap.
- [x] Implement kill switch (manual + auto threshold).
- [x] Add config validation on startup.

Exit criteria:
- Replay tests show deterministic decision outputs with no risk rule violations.

## Phase 3: Execution Engine
- [x] Implement market metadata cache (token IDs, market status, tick sizes).
- [x] Build order submit path with idempotency keys.
- [x] Support `marketable_limit` default execution mode.
- [x] Handle rejects/timeouts with bounded retries.
- [x] Track ack/fill lifecycle and partial fills.
- [x] Ensure coalesced intents create deterministic client order IDs.

Exit criteria:
- Paper trading simulation: >= 98% successful order submissions under normal conditions.

## Phase 4: Latency Instrumentation & SLOs
- [x] Add stage timers:
  - [x] event_receive_ts
  - [x] decision_ts
  - [x] order_submit_ts
  - [x] ack_ts/fill_ts
- [x] Export p50/p95/p99 dashboards.
- [x] Add alerts for:
  - [x] websocket disconnect duration
  - [x] order reject spike
  - [x] p95 latency breach
- [ ] Benchmark from Netherlands VPS and record RTT/latency baseline.
- [x] Track coalescing efficiency metric (source fills -> destination orders ratio).

Exit criteria:
- 7-day run with stable metrics and documented baseline.

## Phase 5: Hardening for Production
- [x] Secrets management (no plaintext secrets in repo).
- [x] Add restart-safe persistence and crash recovery tests.
- [x] Add integration tests for:
  - [x] duplicate events
  - [x] out-of-order events
  - [x] partial outage
- [ ] Add deployment:
  - [ ] systemd service
  - [ ] log rotation
  - [ ] startup dependency checks
- [ ] Incident runbook (`RUNBOOK.md`) for common failures.

Exit criteria:
- Bot can run unattended with recovery procedures validated.

## Phase 6: Rust Migration Decision Gate (Optional)
- [ ] Compare measured p95/p99 latency and jitter against targets.
- [ ] Profile Python hot path (CPU, GC pauses, queue backpressure).
- [ ] If needed, reimplement watcher + executor in Rust.
- [ ] Keep shared protocol/state schema stable across languages.

Exit criteria:
- Decision memo: stay Python or hybrid/full Rust based on measured bottlenecks.

## Immediate Next 10 Tasks
- [x] Pick API endpoints + auth flow.
- [x] Define config schema for `intent_net` copy mode + risk caps.
- [x] Define `TradeEvent`, `ExecutionIntent`, and `RiskSnapshot` schemas.
- [x] Add 15-minute market window fields to `TradeEvent`.
- [x] Implement watcher websocket client with reconnect.
- [x] Add event dedupe store (sqlite).
- [x] Implement intent-net coalescing queue (`coalesce_ms=300` default).
- [x] Add dry-run mode that logs intents and blocked reasons.
- [x] Implement capped proportional sizing + near-expiry/window caps.
- [ ] Run first live paper session on VPS and collect burst and coalescing metrics.
