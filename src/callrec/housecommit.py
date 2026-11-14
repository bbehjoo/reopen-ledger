"""House commits (METHODS.md section 7): what each house forecaster records, the idempotency check, and
the send. One transaction per forecaster per window; a window already on the record is never sent twice.

  null         p = 0.5 on every slate token, no point call
  persistence  p = 0.5 and a point call of 0 bps on every slate token ("no change from the start value")
  dex_implied  the DEX-implied probability and point call on every slate token; where the DEX baseline is
               void the call is p = 0.5 with no point call (the baseline's own rule, METHODS.md section 6)
  coverage     schema 2, the Friday coverage call (coverage.py)
  anchor       schema 3, the daily export hash (export.py)
"""

from __future__ import annotations

import time

from . import attribution, commits, house, tx
from .calendar import Window

LOOKBACK_S = 3 * 86_400   # an existing record is searched from cutoff - 3 days to the head


def _logs_rpc(n: tx.Net):
    """Mainnet log queries go to the `logs` role (publicnode first): the `state` role's first endpoint,
    mainnet.base.org, answers eth_getLogs with rate-limit errors (a 3-day search took 64 s against 35 s)."""
    if n.name == "base":
        from . import config
        from .rpcpool import RpcPool
        return RpcPool(config.rpc_urls("logs"))
    return n.rpc


def existing(n: tx.Net, ledger_addr: str, committer: str, window: int, schema: int, since_block: int) -> list:
    topics = [commits.COMMITTED_TOPIC, "0x" + committer.lower().removeprefix("0x").rjust(64, "0"),
              "0x" + f"{window:064x}", "0x" + f"{schema:064x}"]
    r = _logs_rpc(n)
    head = int(r.call("eth_blockNumber"), 16)
    if since_block > head:
        return []
    return r.get_logs(ledger_addr, topics, since_block, head)


HOUR_MS = 3_600_000


def since_block_for(n: tx.Net, w: Window | None, ledger_entry: dict, since_ms: int | None = None) -> int:
    """First block worth searching for an existing house record: the deploy block, or one hour before the
    earliest moment the house sends that record. House records go out only inside their slots (housedue):
    a daily window's in the hour before its cutoff, a closed window's from its span start. An anchor
    (w None) passes since_ms, the start of its export date; without it the last LOOKBACK_S is searched."""
    deploy = int(ledger_entry.get("block", 0))
    if n.name == "base":
        from .chain import schedule
        if w is not None:   # earliest house send: the span start, or 12 h before a daily cutoff (housedue)
            ref_ms = min(w.start_ms, w.cutoff_ms - 12 * HOUR_MS) - HOUR_MS
        elif since_ms is not None:
            ref_ms = since_ms - HOUR_MS
        else:
            ref_ms = int(time.time() * 1000) - LOOKBACK_S * 1000
        return max(deploy, schedule().block_at_or_before_ms(ref_ms))
    return deploy


def suffix_for(ledger_entry: dict, extra_codes: list[str] | None = None) -> bytes:
    own = ledger_entry.get("builder_code") or attribution.project_code()
    codes = [c for c in [own] + list(extra_codes or []) if c]
    return attribution.to_suffix(codes) if codes else b""


CHECKER = "https://builder-code-checker.vercel.app/api/check"


def official_check(tx_hash: str, tries: int = 3) -> dict:
    """Ask Base's Builder Code checker (the page at builder-code-checker.vercel.app, its own /api/check)
    whether a mainnet transaction is attributed. Best effort: an unreachable checker returns an error
    entry and never blocks a record."""
    import httpx
    err = None
    for i in range(tries):
        try:
            r = httpx.post(CHECKER, json={"hash": tx_hash, "type": "transaction"}, timeout=30)
            d = r.json()
            if d.get("success"):
                return {k: v for k, v in d.items() if k not in ("inputData",)}
            err = d.get("error") or f"HTTP {r.status_code}"
        except Exception as e:   # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:200]
        time.sleep(5 * (i + 1))
    return {"success": False, "error": err}


def attribution_on_chain(n: tx.Net, tx_hash: str) -> list[str] | None:
    """The Builder Codes in a sent transaction's calldata, read back from the chain."""
    t = n.rpc.call("eth_getTransactionByHash", [tx_hash])
    return attribution.from_calldata(t["input"]) if t else None


def commit(network: str, role: str, window: Window | None, window_id: int, schema: int, data: bytes,
           mnemonic: str | None = None, dry_run: bool = False, now_ms: int | None = None,
           since_ms: int | None = None) -> dict:
    n = tx.net(network)
    entry = tx.ledger(network)
    acct = house.derive(mnemonic or house.mnemonic_from_env(), role)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if window is not None and now_ms > window.cutoff_ms:
        return {"status": "skipped_past_cutoff", "role": role, "window": window_id}
    found = existing(n, entry["address"], acct.address, window_id, schema,
                     since_block_for(n, window, entry, since_ms))
    if found:
        return {"status": "already_committed", "role": role, "window": window_id,
                "tx": found[0]["transactionHash"]}
    cd = commits.commit_calldata(window_id, schema, data, suffix_for(entry))
    if dry_run:
        return {"status": "dry_run", "role": role, "window": window_id, "committer": acct.address,
                "calldata_bytes": len(cd) // 2 - 1}
    rc = tx.send(n, acct, entry["address"], cd)
    out = {"status": "sent", "role": role, "window": window_id, "tx": rc["transactionHash"],
           "block": int(rc["blockNumber"], 16), "gas_used": int(rc["gasUsed"], 16),
           "attribution": attribution_on_chain(n, rc["transactionHash"])}
    if network == "base":
        out["official_check"] = official_check(rc["transactionHash"])
    return out


def deployed(network: str) -> bool:
    return network in tx.ledgers(network)


def pending(network: str, slots, mnemonic: str | None = None, now_ms: int | None = None) -> list[dict]:
    """The due slots (housedue.due_slots) whose record is not on the chain yet; read-only."""
    n = tx.net(network)
    entry = tx.ledger(network)
    m = mnemonic or house.mnemonic_from_env()
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    out = []
    for w, role, schema in slots:
        if now_ms > w.cutoff_ms:
            continue
        acct = house.derive(m, role)
        if not existing(n, entry["address"], acct.address, w.id, schema, since_block_for(n, w, entry)):
            out.append({"role": role, "window": w.id, "schema": schema})
    return out


def calls_for(role: str, slate: list[str], baseline: dict[str, dict] | None = None) -> list[commits.Call]:
    if role == "null":
        return [commits.Call(t, 5000, None) for t in slate]
    if role == "persistence":
        return [commits.Call(t, 5000, 0) for t in slate]
    if role == "dex_implied":
        out = []
        for t in slate:
            b = (baseline or {}).get(t)
            if b and b.get("void") is None and b.get("ret_bps") is not None:
                out.append(commits.Call(t, int(round(b["p"] * 10_000)), int(round(b["ret_bps"]))))
            else:
                out.append(commits.Call(t, 5000, None))
        return out
    raise ValueError(f"role {role!r} does not make probability calls")
