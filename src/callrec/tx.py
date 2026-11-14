"""Signing and sending the only transactions this project makes: deploying CallLedger, house commits, the
daily anchor, and gas top-ups between house wallets. Keys come from house.derive(); they are never
printed. Every send prints the network, sender, target and transaction hash only.

Networks (config/ledger.yaml holds the deployed address per network):
  local    anvil on 127.0.0.1:8545 (chain 31337)
  sepolia  Base Sepolia (84532)
  base     Base mainnet (8453)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config
from .rpcpool import RpcPool

NETWORKS = {
    "local": {"chain_id": 31337, "rpc": ["http://127.0.0.1:8545"]},
    "sepolia": {"chain_id": 84532, "rpc": None},   # config/chain.yaml rpc.sepolia
    "base": {"chain_id": 8453, "rpc": None},       # config/chain.yaml rpc.state
}


class TxError(RuntimeError):
    pass


@dataclass
class Net:
    name: str
    chain_id: int
    rpc: object


def net(name: str) -> Net:
    if name not in NETWORKS:
        raise TxError(f"unknown network {name!r}")
    spec = NETWORKS[name]
    urls = spec["rpc"] or config.rpc_urls("sepolia" if name == "sepolia" else "state")
    if name == "local":
        from .rpc import Rpc
        rpc = Rpc(urls[0], min_interval=0.0)
    else:
        rpc = RpcPool(urls)
    got = int(rpc.call("eth_chainId"), 16)
    if got != spec["chain_id"]:
        raise TxError(f"{name}: endpoint answers chain {got}, expected {spec['chain_id']}")
    return Net(name, spec["chain_id"], rpc)


def balance(n: Net, address: str) -> int:
    return int(n.rpc.call("eth_getBalance", [address, "latest"]), 16)


def _fees(n: Net) -> tuple[int, int]:
    base = int(n.rpc.call("eth_getBlockByNumber", ["latest", False])["baseFeePerGas"], 16)
    try:
        tip = int(n.rpc.call("eth_maxPriorityFeePerGas"), 16)
    except Exception:
        tip = 1_000_000  # 0.001 gwei
    tip = max(tip, 1_000)
    return 2 * base + tip, tip


def send(n: Net, account, to: str | None, data: str, value: int = 0, gas: int | None = None,
         wait: bool = True) -> dict:
    """Sign and send one EIP-1559 transaction; returns the receipt (or {'hash'} when not waiting)."""
    from eth_utils import to_checksum_address
    frm = account.address
    to = to_checksum_address(to) if to else None
    nonce = int(n.rpc.call("eth_getTransactionCount", [frm, "pending"]), 16)
    tx_call = {"from": frm, "data": data, "value": hex(value)}
    if to:
        tx_call["to"] = to
    if gas is None:
        gas = int(int(n.rpc.call("eth_estimateGas", [tx_call]), 16) * 1.25) + 5_000
    max_fee, tip = _fees(n)
    tx = {"chainId": n.chain_id, "nonce": nonce, "gas": gas, "maxFeePerGas": max_fee,
          "maxPriorityFeePerGas": tip, "value": value, "data": data, "type": 2}
    if to:
        tx["to"] = to
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = n.rpc.call("eth_sendRawTransaction", ["0x" + raw.hex().removeprefix("0x")])
    print(f"[{n.name}] sent {h} from {frm} to {to or '(create)'}")
    if not wait:
        return {"transactionHash": h}
    for _ in range(180):
        rc = n.rpc.call("eth_getTransactionReceipt", [h])
        if rc:
            if int(rc["status"], 16) != 1:
                raise TxError(f"[{n.name}] transaction {h} reverted")
            return rc
        time.sleep(1)
    raise TxError(f"[{n.name}] no receipt for {h} after 180 s")


# --- the deployed ledger per network ------------------------------------------------------------------
def ledger_file(network: str | None = None) -> Path:
    """config/ledger.yaml (committed) for sepolia and base; a scratch file for the throwaway local chain."""
    if network == "local":
        p = config.data_dir() / "scratch" / "ledger-local.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return config.config_dir() / "ledger.yaml"


def ledgers(network: str | None = None) -> dict:
    p = ledger_file(network)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def ledger(name: str) -> dict:
    d = ledgers(name).get(name)
    if not d:
        raise TxError(f"no CallLedger recorded for {name} (run `callrec ledger deploy --network {name}`)")
    return d


def record_ledger(name: str, entry: dict) -> None:
    d = ledgers(name)
    d[name] = entry
    head = "# CallLedger deployments, written by `callrec ledger deploy`. One entry per network.\n"
    ledger_file(name).write_text(head + yaml.safe_dump(d, sort_keys=True), encoding="utf-8", newline="\n")


ARTIFACT = config.ROOT / "contracts" / "artifacts" / "CallLedger.json"


def artifact() -> dict:
    """The committed build of CallLedger (contracts/artifacts, written from `forge build`; a test checks it
    against contracts/out and the source hash), so CI deploys exactly the bytecode tested here."""
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def artifact_bytecode() -> str:
    return artifact()["bytecode"]


def deployed_code(n: Net, address: str, block: str | int = "latest") -> str:
    tag = hex(block) if isinstance(block, int) else block
    return n.rpc.call("eth_getCode", [address, tag])


def create_address(sender: str, nonce: int) -> str:
    """The CREATE address of `sender`'s transaction `nonce` (keccak(rlp([sender, nonce]))[12:])."""
    from eth_utils import keccak, to_checksum_address
    if not 0 <= nonce < 0x80:
        raise ValueError("nonce out of the one-byte range handled here")
    rlp = bytes([0xD6, 0x94]) + bytes.fromhex(sender.lower().removeprefix("0x")) + (bytes([nonce]) if nonce else b"\x80")
    return to_checksum_address(keccak(rlp)[12:])


def _deploy_block(n: Net, address: str, hi: int) -> int:
    """First block at which `address` has code (binary search over historical eth_getCode)."""
    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        if deployed_code(n, address, mid) not in ("0x", "0x0", ""):
            hi = mid
        else:
            lo = mid + 1
    return lo


def deploy_or_recover(network: str, account, builder_code: str | None) -> dict:
    """Deploy CallLedger from the anchor wallet's first transaction (nonce 0), or, when that transaction was
    already sent (a job that died before recording it), find the contract it created and record that. A
    second contract is never deployed: an anchor wallet whose nonce-0 address holds other code is an error."""
    n = net(network)
    if network in ledgers(network):
        return {**ledger(network), "status": "already_recorded"}
    target = create_address(account.address, 0)
    want = artifact()["deployed_bytecode"].lower()
    sent = int(n.rpc.call("eth_getTransactionCount", [account.address, "latest"]), 16)
    pending = int(n.rpc.call("eth_getTransactionCount", [account.address, "pending"]), 16)
    if sent == 0 and pending == 0:
        rc = send(n, account, None, artifact_bytecode())
        if rc["contractAddress"].lower() != target.lower():
            raise TxError(f"[{network}] deploy created {rc['contractAddress']}, expected {target}")
        status, block, txh = "deployed", int(rc["blockNumber"], 16), rc["transactionHash"]
    else:
        for _ in range(180):   # a deploy may still be pending from an earlier run
            if deployed_code(n, target) not in ("0x", ""):
                break
            time.sleep(1)
        code = deployed_code(n, target).lower()
        if code != want:
            raise TxError(f"[{network}] anchor wallet has sent {sent} transaction(s) but {target} does not hold "
                          "CallLedger; nothing deployed (fix by hand, RUNBOOK section 3)")
        head = int(n.rpc.call("eth_blockNumber"), 16)
        block = _deploy_block(n, target, head)
        blk = n.rpc.call("eth_getBlockByNumber", [hex(block), True])
        txh = next((t["hash"] for t in blk["transactions"] if t["from"].lower() == account.address.lower()
                    and not t.get("to")), None)
        status = "recovered"
    code = deployed_code(n, target).lower()
    if code != want:
        raise TxError(f"[{network}] runtime code at {target} differs from contracts/artifacts/CallLedger.json")
    entry = {"address": target, "block": block, "tx": txh, "deployer": account.address, "chain_id": n.chain_id,
             "runtime_code_bytes": len(code) // 2 - 1}
    if builder_code:
        entry["builder_code"] = builder_code
    record_ledger(network, entry)
    return {**entry, "status": status}
