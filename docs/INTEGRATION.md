# Polymarket Integration (v1)

## Scope
This document pins the integration surface for the copy bot MVP.

## Base Endpoints
- CLOB REST: `https://clob.polymarket.com`
- Data API: `https://data-api.polymarket.com`
- Gamma API: `https://gamma-api.polymarket.com`
- CLOB WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/`

## Source Wallet Ingestion Path
Primary (v1):
- Poll Data API activity for source wallet:
  - `GET /activity`
  - Required query: `user=<0x wallet>`
  - Filter query: `type=TRADE`, optional `side=BUY|SELL`

Secondary/backfill:
- Data API positions:
  - `GET /positions?user=<0x wallet>`
- CLOB trades for self-account checks:
  - `GET /data/trades` (L2 auth required)

Rationale:
- Source wallet is a third-party wallet, so we cannot use authenticated user WSS for that wallet.
- Data API activity gives trade-level history for arbitrary wallets.

## Execution Path
- Use CLOB client with authenticated account to sign and post orders.
- Default order style: marketable limit order with slippage cap.

## Auth Flow
Authentication layers:
1. L1 (wallet private key / EIP-712) to create or derive API creds.
2. L2 (apiKey, secret, passphrase / HMAC-SHA256) for authenticated CLOB endpoints.

Key steps:
1. Load signer private key and funder address.
2. Create or derive L2 API credentials via CLOB auth endpoints.
3. Initialize client with signer + L2 creds + signature type.
4. Submit signed orders.

## Relevant Endpoints (v1)
- L1 create API key: `POST /auth/api-key`
- L1 derive API key: `GET /auth/derive-api-key`
- Place order: `POST /order`
- Cancel order: `DELETE /order`
- Get order: `GET /data/order/<order_hash>`
- Get own trades: `GET /data/trades`
- Get source wallet activity: `GET https://data-api.polymarket.com/activity`

## Operational Notes
- Keep system clock synced (NTP) for signed request timestamps.
- Respect Data API and CLOB rate limits.
- Keep auth secrets only in environment variables, never in git.

## Sources
- https://docs.polymarket.com/developers/CLOB/authentication
- https://docs.polymarket.com/quickstart/reference/endpoints
- https://docs.polymarket.com/developers/misc-endpoints/data-api-activity
- https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
- https://docs.polymarket.com/developers/CLOB/websocket/wss-auth
