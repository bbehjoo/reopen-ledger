"""Reopen Ledger as a Coinbase AgentKit action (Python, coinbase-agentkit).

    from reopen_ledger_action import ReopenLedgerActionProvider
    agentkit = AgentKit(AgentKitConfig(wallet_provider=..., action_providers=[ReopenLedgerActionProvider()]))

The action `reopen_ledger_commit` puts one prediction on the record: a probability per token that it reopens
higher, for one window (ids and slates: https://bbehjoo.github.io/reopen-ledger/data/form.json). Your Builder
Codes go first in the ERC-8021 suffix, then the project's, so the transaction counts for both. Use a wallet
provider that sends ordinary transactions (CdpEvmWalletProvider, EthAccountWalletProvider): a smart-wallet
provider wraps the call and the suffix would not sit where Base reads it.
"""
from __future__ import annotations

import math
from typing import Any

LEDGER = "0x32E9d4e3c865b802689D39caAA30c7328de281C0"
SELECTOR = "eda6e22e"  # commit(uint32,uint16,bytes)
MARKER = "80218021802180218021802180218021"
PROJECT_CODES = ["bc_akq83qpj"]


def encode(window_id: int, calls: list[dict], builder_codes: list[str]) -> str:
    """Calldata for commit(window_id, 1, data) plus the ERC-8021 suffix (METHODS.md section 4)."""
    body = b"".join(bytes.fromhex(c["token"][2:].lower()) + math.floor(float(c["p"]) * 10000 + 0.5).to_bytes(2, "big")
                    + bytes.fromhex("80000000") for c in sorted(calls, key=lambda c: c["token"].lower()))
    pad = (32 - len(body) % 32) % 32
    abi = (window_id.to_bytes(32, "big") + (1).to_bytes(32, "big") + (96).to_bytes(32, "big")
           + len(body).to_bytes(32, "big") + body + b"\0" * pad)
    data = "0x" + SELECTOR + abi.hex()
    codes = list(builder_codes) + [c for c in PROJECT_CODES if c not in builder_codes]
    if codes:
        raw = ",".join(codes).encode("ascii")
        data += (raw + bytes([len(raw), 0])).hex() + MARKER
    return data


try:  # the AgentKit wrapper is optional: `encode` above has no dependencies
    from coinbase_agentkit import ActionProvider, EvmWalletProvider, create_action
    from coinbase_agentkit.network import Network
    from pydantic import BaseModel, Field

    class Call(BaseModel):
        token: str
        p: float = Field(ge=0, le=1)

    class CommitSchema(BaseModel):
        windowId: int
        calls: list[Call]
        builderCodes: list[str] | None = None

    class ReopenLedgerActionProvider(ActionProvider[EvmWalletProvider]):
        def __init__(self):
            super().__init__("reopen_ledger", [])

        @create_action(name="reopen_ledger_commit",
                       description="Put a prediction on the Reopen Ledger record on Base: for one window, the "
                                   "probability each token reopens higher. Value 0; the contract holds no funds.",
                       schema=CommitSchema)
        def commit(self, wallet_provider: EvmWalletProvider, args: dict[str, Any]) -> str:
            a = CommitSchema(**args)
            data = encode(a.windowId, [c.model_dump() for c in a.calls], a.builderCodes or [])
            h = wallet_provider.send_transaction({"to": LEDGER, "data": data, "value": 0})
            wallet_provider.wait_for_transaction_receipt(h)
            return f"On the record for window {a.windowId}: https://basescan.org/tx/{h}"

        def supports_network(self, network: Network) -> bool:
            return network.protocol_family == "evm" and str(network.chain_id) == "8453"
except ImportError:
    pass
