# Coinbot Runbook

## Service Control
- Start: `sudo systemctl start coinbot`
- Stop: `sudo systemctl stop coinbot`
- Restart: `sudo systemctl restart coinbot`
- Status: `sudo systemctl status coinbot`
- Logs: `tail -f /var/log/coinbot/coinbot.log`

## Common Incidents

### 1) Websocket Disconnect Duration Alert
Symptoms:
- `alert_ws_disconnect=true`
- Missing source events

Actions:
1. Check network health from VPS:
   - `ping -c 5 ws-subscriptions-clob.polymarket.com`
2. Restart service:
   - `sudo systemctl restart coinbot`
3. Validate checkpoint movement in sqlite store:
   - `sqlite3 data/coinbot.db 'select * from checkpoints;'`

### 2) Reject Spike Alert
Symptoms:
- `alert_reject_spike=true`
- Frequent `order_submit_retry` logs

Actions:
1. Confirm API credentials and dry-run flag.
2. Reduce aggressiveness:
   - lower `SIZING_SIZE_MULTIPLIER`
   - tighten `SIZING_MAX_NOTIONAL_PER_ORDER_USD`
3. Temporarily enable kill switch and investigate market status.

### 3) High p95 Copy Delay Alert
Symptoms:
- `alert_p95_latency=true`

Actions:
1. Check VPS CPU/memory pressure.
2. Check endpoint latency to CLOB/Data API.
3. Increase coalescing slightly (`COPY_COALESCE_MS`) only if queue pressure is high.
4. If sustained, keep dry-run and capture telemetry snapshot for profiling.

### 4) Crash / Restart Recovery
Symptoms:
- service exits and restarts repeatedly

Actions:
1. Run startup checks manually:
   - `./scripts/startup-check.sh`
2. Validate config:
   - `PYTHONPATH=src python3 -m coinbot.main`
3. Confirm sqlite file is writable:
   - `ls -l data/`

## Safe Mode
To disable live execution quickly:
1. Set `EXECUTION_DRY_RUN=true` in `.env`.
2. Restart service.

## Escalation Notes
- Capture last 200 log lines and telemetry snapshot fields.
- Record exact UTC timestamp and wallet being copied.
