# Build TODO (Latency-First)

## Phase 0: Foundation
- [ ] Confirm Polymarket API/auth/event interfaces to use for source wallet tracking.
- [ ] Decide runtime for MVP: Python async stack (recommended first).
- [ ] Create `.env.example` with required secrets and config keys.
- [ ] Set source wallet config default to `0x1d0034134e339a309700ff2d34e99fa2d48b0313`.
- [ ] Add replication config keys and defaults:
  - [ ] `copy_mode=intent_net`
  - [ ] `coalesce_ms=300`
  - [ ] `net_opposite_trades=true`
  - [ ] `near_expiry_cutoff_seconds=25`
  - [ ] `max_notional_per_order_usd=25`
  - [ ] `max_notional_per_market_usd=150`
  - [ ] `max_total_notional_per_15m_window_usd=400`
- [ ] Set up project skeleton:
  - [ ] `src/watcher`
  - [ ] `src/decision_engine`
  - [ ] `src/executor`
  - [ ] `src/state_store`
  - [ ] `src/telemetry`
- [ ] Add structured logging and request/event correlation IDs.

Exit criteria:
- Local service boots and all modules initialize with health checks.

## Phase 1: Source Wallet Event Ingestion
- [ ] Implement websocket subscription(s) for source wallet activity.
- [ ] Normalize incoming events into internal `TradeEvent` schema.
- [ ] Include market window metadata in normalized events (asset, start/end, outcome side).
- [ ] Add deduplication by event ID + tx hash + sequence rules.
- [ ] Persist last processed offsets/checkpoints.
- [ ] Implement reconnect logic with exponential backoff and replay safety.

Exit criteria:
- In paper mode, all source wallet trades are captured and normalized without duplicates for 48h.

## Phase 2: Decision + Risk Engine
- [ ] Implement sizing modes:
  - [ ] Fixed size
  - [ ] Proportional
  - [ ] Capped proportional (default)
- [ ] Add hard risk checks:
  - [ ] Max order notional
  - [ ] Max market exposure
  - [ ] Max daily traded volume
- [ ] Implement burst coalescing (same market + same outcome + short window) before execution.
- [ ] Add near-expiry guard (do not open new copied positions in final N seconds of 15m market).
- [ ] Add optional netting mode for rapid opposite trades in same market window.
- [ ] Add intent-net aggregator keyed by `(market_id, outcome, window_id)`.
- [ ] Drop intents below `min_order_notional_usd`.
- [ ] Enforce `max_total_notional_per_15m_window_usd` cap.
- [ ] Implement kill switch (manual + auto threshold).
- [ ] Add config validation on startup.

Exit criteria:
- Replay tests show deterministic decision outputs with no risk rule violations.

## Phase 3: Execution Engine
- [ ] Implement market metadata cache (token IDs, market status, tick sizes).
- [ ] Build order submit path with idempotency keys.
- [ ] Support `marketable_limit` default execution mode.
- [ ] Handle rejects/timeouts with bounded retries.
- [ ] Track ack/fill lifecycle and partial fills.
- [ ] Ensure coalesced intents create deterministic client order IDs.

Exit criteria:
- Paper trading simulation: >= 98% successful order submissions under normal conditions.

## Phase 4: Latency Instrumentation & SLOs
- [ ] Add stage timers:
  - [ ] event_receive_ts
  - [ ] decision_ts
  - [ ] order_submit_ts
  - [ ] ack_ts/fill_ts
- [ ] Export p50/p95/p99 dashboards.
- [ ] Add alerts for:
  - [ ] websocket disconnect duration
  - [ ] order reject spike
  - [ ] p95 latency breach
- [ ] Benchmark from Netherlands VPS and record RTT/latency baseline.
- [ ] Track coalescing efficiency metric (source fills -> destination orders ratio).

Exit criteria:
- 7-day run with stable metrics and documented baseline.

## Phase 5: Hardening for Production
- [ ] Secrets management (no plaintext secrets in repo).
- [ ] Add restart-safe persistence and crash recovery tests.
- [ ] Add integration tests for:
  - [ ] duplicate events
  - [ ] out-of-order events
  - [ ] partial outage
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
- [ ] Pick API endpoints + auth flow.
- [ ] Define config schema for `intent_net` copy mode + risk caps.
- [ ] Define `TradeEvent`, `ExecutionIntent`, and `RiskSnapshot` schemas.
- [ ] Add 15-minute market window fields to `TradeEvent`.
- [ ] Implement watcher websocket client with reconnect.
- [ ] Add event dedupe store (sqlite).
- [ ] Implement intent-net coalescing queue (`coalesce_ms=300` default).
- [ ] Add dry-run mode that logs intents and blocked reasons.
- [ ] Implement capped proportional sizing + near-expiry/window caps.
- [ ] Run first live paper session on VPS and collect burst and coalescing metrics.
