from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from threading import Event
from typing import Any


CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_CTF_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

CTF_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"internalType": "address", "name": "collateralToken", "type": "address"},
            {"internalType": "bytes32", "name": "parentCollectionId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
            {"internalType": "uint256[]", "name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "conditionId", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

SAFE_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "name": "nonce",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getThreshold",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "isOwner",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "value", "type": "uint256"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
            {"internalType": "uint8", "name": "operation", "type": "uint8"},
            {"internalType": "uint256", "name": "safeTxGas", "type": "uint256"},
            {"internalType": "uint256", "name": "baseGas", "type": "uint256"},
            {"internalType": "uint256", "name": "gasPrice", "type": "uint256"},
            {"internalType": "address", "name": "gasToken", "type": "address"},
            {"internalType": "address", "name": "refundReceiver", "type": "address"},
            {"internalType": "uint256", "name": "nonce", "type": "uint256"},
        ],
        "name": "getTransactionHash",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "value", "type": "uint256"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
            {"internalType": "uint8", "name": "operation", "type": "uint8"},
            {"internalType": "uint256", "name": "safeTxGas", "type": "uint256"},
            {"internalType": "uint256", "name": "baseGas", "type": "uint256"},
            {"internalType": "uint256", "name": "gasPrice", "type": "uint256"},
            {"internalType": "address", "name": "gasToken", "type": "address"},
            {"internalType": "address", "name": "refundReceiver", "type": "address"},
            {"internalType": "bytes", "name": "signatures", "type": "bytes"},
        ],
        "name": "execTransaction",
        "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
        "stateMutability": "payable",
        "type": "function",
    },
]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class AutoRedeemerConfig:
    enabled: bool
    interval_seconds: int
    data_api_url: str
    gamma_api_url: str
    rpc_url: str
    private_key: str
    wallet_address: str
    min_redeemable_shares: float
    dry_run: bool


class AutoRedeemer:
    def __init__(self, cfg: AutoRedeemerConfig) -> None:
        self._cfg = cfg
        self._log = logging.getLogger(self.__class__.__name__)
        self._last_redeemed_by_condition: dict[str, float] = {}
        self._w3 = None
        self._signer_address: str | None = None
        self._wallet_contract = None
        self._redeem_mode = "unknown"

    def run_forever(self, stop_event: Event) -> None:
        if not self._cfg.enabled:
            return
        if not self._cfg.wallet_address:
            self._log.warning("redeemer_disabled_missing_wallet")
            return
        if not self._cfg.private_key:
            self._log.warning("redeemer_disabled_missing_private_key")
            return
        if not self._ensure_runtime_ready():
            return
        self._log.info(
            "redeemer_started wallet=%s interval_s=%s dry_run=%s mode=%s",
            self._cfg.wallet_address,
            self._cfg.interval_seconds,
            self._cfg.dry_run,
            self._redeem_mode,
        )
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self._log.warning("redeemer_cycle_error error=%s", exc)
            stop_event.wait(self._cfg.interval_seconds)

    def run_once(self) -> None:
        positions = self._fetch_wallet_positions()
        if not positions:
            return
        grouped = _group_by_condition(positions)
        for condition_id, rows in grouped.items():
            if not condition_id:
                continue
            if self._recently_redeemed(condition_id):
                continue
            neg_risk = self._condition_neg_risk(condition_id)
            ctf_address = NEG_RISK_CTF_ADDRESS if neg_risk else CTF_ADDRESS
            contract = self._w3.eth.contract(address=ctf_address, abi=CTF_ABI)
            if not self._condition_resolved(contract, condition_id):
                continue
            token_ids = [x for x in {_token_id_from_row(r) for r in rows} if x is not None]
            if not token_ids:
                continue
            total_shares = self._wallet_shares(contract, token_ids)
            if total_shares < self._cfg.min_redeemable_shares:
                continue
            if self._cfg.dry_run:
                self._log.info(
                    "redeemer_dry_run condition=%s shares=%.4f",
                    condition_id[:12],
                    total_shares,
                )
                self._last_redeemed_by_condition[condition_id] = time.time()
                continue
            if self._redeem_positions(contract, condition_id):
                self._last_redeemed_by_condition[condition_id] = time.time()

    def _ensure_runtime_ready(self) -> bool:
        try:
            from web3 import Web3  # type: ignore
        except ModuleNotFoundError:
            self._log.warning("redeemer_disabled_missing_dep dependency=web3")
            return False

        self._w3 = Web3(Web3.HTTPProvider(self._cfg.rpc_url, request_kwargs={"timeout": 10}))
        if not self._w3.is_connected():
            self._log.warning("redeemer_disabled_rpc_unreachable url=%s", self._cfg.rpc_url)
            return False
        acct = self._w3.eth.account.from_key(self._cfg.private_key)
        self._signer_address = str(acct.address)
        if self._signer_address.lower() != self._cfg.wallet_address.lower():
            try:
                wallet_code = self._w3.eth.get_code(self._cfg.wallet_address)
            except Exception as exc:
                self._log.warning(
                    "redeemer_disabled_wallet_code_check_failed wallet=%s error=%s",
                    self._cfg.wallet_address,
                    exc,
                )
                return False
            if not wallet_code:
                self._log.warning(
                    "redeemer_disabled_signer_wallet_mismatch signer=%s wallet=%s",
                    self._signer_address,
                    self._cfg.wallet_address,
                )
                return False
            self._wallet_contract = self._w3.eth.contract(
                address=self._cfg.wallet_address,
                abi=SAFE_ABI,
            )
            try:
                threshold = int(self._wallet_contract.functions.getThreshold().call())
                is_owner = bool(self._wallet_contract.functions.isOwner(self._signer_address).call())
            except Exception as exc:
                self._log.warning("redeemer_disabled_wallet_not_safe wallet=%s error=%s", self._cfg.wallet_address, exc)
                return False
            if not is_owner:
                self._log.warning(
                    "redeemer_disabled_signer_not_safe_owner signer=%s wallet=%s",
                    self._signer_address,
                    self._cfg.wallet_address,
                )
                return False
            if threshold != 1:
                self._log.warning(
                    "redeemer_disabled_unsupported_safe_threshold wallet=%s threshold=%s",
                    self._cfg.wallet_address,
                    threshold,
                )
                return False
            self._redeem_mode = "safe"
            return True
        self._redeem_mode = "direct"
        return True

    def _fetch_wallet_positions(self) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"user": self._cfg.wallet_address})
        url = f"{self._cfg.data_api_url.rstrip('/')}/positions?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, list):
                return [x for x in payload if isinstance(x, dict)]
        except Exception as exc:
            self._log.warning("redeemer_positions_fetch_error error=%s", exc)
        return []

    def _condition_neg_risk(self, condition_id: str) -> bool:
        params = urllib.parse.urlencode({"condition_id": condition_id})
        url = f"{self._cfg.gamma_api_url.rstrip('/')}/markets?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "coinbot/0.1"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, list) and payload:
                market = payload[0]
                if isinstance(market, dict):
                    return bool(market.get("negRisk") or market.get("neg_risk"))
        except Exception:
            pass
        return False

    def _condition_resolved(self, contract: Any, condition_id: str) -> bool:
        try:
            denominator = contract.functions.payoutDenominator(condition_id).call()
            return int(denominator) > 0
        except Exception:
            return False

    def _wallet_shares(self, contract: Any, token_ids: list[int]) -> float:
        total = 0.0
        for token_id in token_ids:
            try:
                raw = contract.functions.balanceOf(self._cfg.wallet_address, token_id).call()
                total += float(raw) / 1_000_000.0
            except Exception:
                continue
        return total

    def _redeem_positions(self, contract: Any, condition_id: str) -> bool:
        try:
            data = contract.encodeABI(
                fn_name="redeemPositions",
                args=[USDC_ADDRESS, "0x" + ("00" * 32), condition_id, [1, 2]],
            )
            if self._redeem_mode == "safe":
                return self._redeem_positions_safe(
                    condition_id=condition_id,
                    target_address=contract.address,
                    data=data,
                )

            nonce = self._w3.eth.get_transaction_count(self._signer_address, "pending")
            gas_estimate = contract.functions.redeemPositions(USDC_ADDRESS, "0x" + ("00" * 32), condition_id, [1, 2]).estimate_gas(
                {"from": self._signer_address}
            )
            tx = contract.functions.redeemPositions(USDC_ADDRESS, "0x" + ("00" * 32), condition_id, [1, 2]).build_transaction(
                {
                    "from": self._signer_address,
                    "chainId": int(self._w3.eth.chain_id),
                    "nonce": int(nonce),
                    "gas": int(gas_estimate * 1.2),
                    "gasPrice": int(self._w3.eth.gas_price),
                }
            )
            signed = self._w3.eth.account.sign_transaction(tx, private_key=self._cfg.private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            if int(receipt.status) == 1:
                self._log.info(
                    "redeemer_redeemed condition=%s tx_hash=%s",
                    condition_id[:12],
                    tx_hash.hex(),
                )
                return True
            self._log.warning(
                "redeemer_redeem_failed condition=%s tx_hash=%s status=%s",
                condition_id[:12],
                tx_hash.hex(),
                receipt.status,
            )
            return False
        except Exception as exc:
            self._log.warning("redeemer_tx_error condition=%s error=%s", condition_id[:12], exc)
            return False

    def _redeem_positions_safe(self, *, condition_id: str, target_address: str, data: str) -> bool:
        try:
            safe_nonce = int(self._wallet_contract.functions.nonce().call())
            safe_tx_hash = self._wallet_contract.functions.getTransactionHash(
                target_address,
                0,
                data,
                0,
                0,
                0,
                0,
                ZERO_ADDRESS,
                ZERO_ADDRESS,
                safe_nonce,
            ).call()
            sig = _sign_hash_no_prefix(self._w3, self._cfg.private_key, safe_tx_hash)
            signatures = _build_safe_signature(sig["r"], sig["s"], sig["v"])

            gas_estimate = self._wallet_contract.functions.execTransaction(
                target_address,
                0,
                data,
                0,
                0,
                0,
                0,
                ZERO_ADDRESS,
                ZERO_ADDRESS,
                signatures,
            ).estimate_gas({"from": self._signer_address})

            tx = self._wallet_contract.functions.execTransaction(
                target_address,
                0,
                data,
                0,
                0,
                0,
                0,
                ZERO_ADDRESS,
                ZERO_ADDRESS,
                signatures,
            ).build_transaction(
                {
                    "from": self._signer_address,
                    "chainId": int(self._w3.eth.chain_id),
                    "nonce": int(self._w3.eth.get_transaction_count(self._signer_address, "pending")),
                    "gas": int(gas_estimate * 1.2),
                    "gasPrice": int(self._w3.eth.gas_price),
                }
            )
            signed = self._w3.eth.account.sign_transaction(tx, private_key=self._cfg.private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            if int(receipt.status) == 1:
                self._log.info(
                    "redeemer_redeemed_safe condition=%s tx_hash=%s",
                    condition_id[:12],
                    tx_hash.hex(),
                )
                return True
            self._log.warning(
                "redeemer_redeem_safe_failed condition=%s tx_hash=%s status=%s",
                condition_id[:12],
                tx_hash.hex(),
                receipt.status,
            )
            return False
        except Exception as exc:
            self._log.warning("redeemer_safe_tx_error condition=%s error=%s", condition_id[:12], exc)
            return False

    def _recently_redeemed(self, condition_id: str) -> bool:
        ts = self._last_redeemed_by_condition.get(condition_id)
        if ts is None:
            return False
        return (time.time() - ts) <= max(self._cfg.interval_seconds * 3, 120)


def _group_by_condition(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        condition_id = str(row.get("conditionId") or row.get("condition_id") or "")
        if not condition_id:
            continue
        grouped.setdefault(condition_id, []).append(row)
    return grouped


def _token_id_from_row(row: dict[str, Any]) -> int | None:
    raw = row.get("asset") or row.get("tokenId") or row.get("token_id")
    if raw is None:
        return None
    try:
        return int(str(raw))
    except Exception:
        return None


def _build_safe_signature(r: int, s: int, v: int) -> bytes:
    v_fixed = v + 27 if v in {0, 1} else v
    return r.to_bytes(32, byteorder="big") + s.to_bytes(32, byteorder="big") + bytes([v_fixed])


def _sign_hash_no_prefix(w3: Any, private_key: str, digest: bytes | str) -> dict[str, int]:
    # Try public helpers first; fall back to lower-level implementations.
    account = w3.eth.account
    if hasattr(account, "signHash"):
        signed = account.signHash(digest, private_key=private_key)
        return {"r": int(signed.r), "s": int(signed.s), "v": int(signed.v)}
    if hasattr(account, "_sign_hash"):
        signed = account._sign_hash(digest, private_key=private_key)
        return {"r": int(signed.r), "s": int(signed.s), "v": int(signed.v)}
    from eth_keys import keys

    digest_bytes = digest if isinstance(digest, bytes) else w3.to_bytes(hexstr=digest)
    key_hex = private_key[2:] if private_key.startswith("0x") else private_key
    pk = keys.PrivateKey(bytes.fromhex(key_hex))
    sig = pk.sign_msg_hash(digest_bytes)
    return {"r": int(sig.r), "s": int(sig.s), "v": int(sig.v) + 27}
