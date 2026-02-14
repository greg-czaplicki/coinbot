# coinbot

Polymarket copy-trading bot focused on low-latency intent-level replication.

## Quick Commands
- Boot dry-run: `PYTHONPATH=src python3 -m coinbot.main`
- Run recovery/integration tests: `PYTHONPATH=src python3 -m unittest tests.test_recovery tests.test_integration_flows`
- Benchmark endpoint latency on VPS: `./scripts/benchmark-latency.sh 30 docs/LATENCY_BASELINE.md`
- Run a timed paper session: `./scripts/live-paper.sh 60`

## Telemetry Files
- CSV snapshots: `runs/telemetry/snapshots.csv`
- JSONL snapshots: `runs/telemetry/snapshots.jsonl`
