#!/usr/bin/env python3
"""Reopen Ledger starter agent (Python 3.11+, web3 and eth-account; form.json is read with urllib).

Puts one record on the CallLedger contract on Base: commit(windowId, 1, data), where data holds one
probability per slate token that its Chainlink reference value ends the window above where it started.
The contract holds no funds and the transaction carries no value; it only emits an event.

  python agent.py --dry-run            print the window, the probabilities and the calldata; send nothing
  python agent.py                      send the record (needs PRIVATE_KEY and a little ETH on Base for gas)
  python agent.py --kind daily         only consider daily windows (kind 2); --kind closed for kind 1
  python agent.py --window 220261117   a specific open window
  python agent.py --dry-run --fixture  fixed example (no network), used by verify.py

Env: PRIVATE_KEY (hex, the wallet that signs) or, with no key anywhere, CDP_API_KEY_ID / CDP_API_KEY_SECRET /
     CDP_WALLET_SECRET for a Coinbase server account (pip install cdp-sdk; --account prints its address),
     BUILDER_CODES (yours, comma separated, optional), STRATEGY / CONFIDENCE (see predict()),
     RPC_URL (default https://mainnet.base.org), FORM_URL (default the live site's data/form.json).

The encoding is self-contained on purpose (the same bytes as the site's commit.js, METHODS.md section 4),
so this file can be copied anywhere on its own. web3 and eth-account are imported only when sending.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request

FORM_URL = os.environ.get("FORM_URL") or "https://bbehjoo.github.io/reopen-ledger/data/form.json"
RPC_URL = os.environ.get("RPC_URL") or "https://mainnet.base.org"
EXPECTED_LEDGER = "0x32e9d4e3c865b802689d39caaa30c7328de281c0"
CHAIN_ID = 8453
MARGIN_MS = 120_000  # leave two minutes for the transaction to be mined before the cutoff


# =====================================================================================================
# YOUR MODEL GOES HERE.
# Return, for each slate token address, the probability (0 to 1) that its Chainlink reference value at the
# window's end is above its value at the window's start. Tokens you leave out are scored as 0.5.
#
# Two starting strategies, chosen with the STRATEGY env:
#   weekend_dex (default)  reads the DEX price against the Chainlink reference as odds, the way the Weekend
#                          DEX rival does: p = Phi(gap / sigma). CONFIDENCE scales the gap (1.0 = the rival;
#                          0.7 = humbler, 1.3 = bolder). Change it, add signals, beat the rival.
#   coin_flip              0.5 for everything; scores exactly like the Coin Flip rival.
# =====================================================================================================
STRATEGY = os.environ.get("STRATEGY") or "weekend_dex"
CONFIDENCE = float(os.environ.get("CONFIDENCE") or 1.0)


def predict(slate: list[dict], window: dict) -> dict[str, float]:
    if STRATEGY == "coin_flip":
        return {t["address"]: 0.5 for t in slate}
    if STRATEGY == "weekend_dex":
        return weekend_dex(slate, window, CONFIDENCE)
    raise SystemExit(f"error: unknown STRATEGY {STRATEGY!r} (weekend_dex or coin_flip)")


# ---- the weekend_dex strategy: public data only, no keys ----
DEX_URL = "https://api.dexscreener.com/tokens/v1/base/"


def _get_json(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "reopen-ledger-agent",
                                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def reference_value(feed: dict) -> float | None:
    """Chainlink latestRoundData().answer on Base, scaled by the feed's decimals."""
    try:
        res = _get_json(RPC_URL, {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                  "params": [{"to": feed["proxy"], "data": "0xfeaf968c"}, "latest"]})["result"]
        answer = int(res[2 + 64: 2 + 128], 16)
        if answer >= 1 << 255:
            answer -= 1 << 256
        return answer / 10 ** int(feed.get("decimals", 8)) if answer > 0 else None
    except Exception:  # noqa: BLE001  any read failure leaves this token at 0.5
        return None


def dex_prices(addresses: list[str]) -> dict[str, float]:
    """USD price of each token from its most liquid Base pool (DexScreener's public API)."""
    out: dict[str, tuple[float, float]] = {}
    for i in range(0, len(addresses), 30):
        try:
            pairs = _get_json(DEX_URL + ",".join(addresses[i:i + 30]))
        except Exception:  # noqa: BLE001
            continue
        for pr in pairs if isinstance(pairs, list) else []:
            a = (pr.get("baseToken") or {}).get("address", "").lower()
            liq = float((pr.get("liquidity") or {}).get("usd") or 0)
            if a and pr.get("priceUsd") and liq > out.get(a, (0.0, -1.0))[1]:
                out[a] = (float(pr["priceUsd"]), liq)
    return {a: v[0] for a, v in out.items()}


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def weekend_dex(slate: list[dict], window: dict, confidence: float = 1.0) -> dict[str, float]:
    """p = Phi(confidence x gap_bps / sigma), gap = ln(DEX price / reference), clipped to [0.05, 0.95];
    0.5 where a price is missing or the DEX is more than 30% from the reference (a broken or empty pool).
    The rival uses the last-hour TWAP of the primary pool; this uses the most liquid pool's spot price."""
    sigma = float(window.get("sigma_bps") or 150.0)
    dex = dex_prices([t["address"].lower() for t in slate])
    out = {}
    for t in slate:
        a, feed = t["address"].lower(), t.get("reference_feed")
        ref = reference_value(feed) if feed else None
        price = dex.get(a)
        if not ref or not price or abs(price / ref - 1) > 0.30:
            out[t["address"]] = 0.5
            continue
        gap_bps = math.log(price / ref) * 10_000
        out[t["address"]] = round(min(0.95, max(0.05, phi(confidence * gap_bps / sigma))), 4)
    return out


# ---- encoding: commit(uint32,uint16,bytes), schema 1, plus the ERC-8021 attribution suffix ----
SELECTOR = "eda6e22e"  # first 4 bytes of keccak256("commit(uint32,uint16,bytes)")
MARKER = "80218021802180218021802180218021"
RET_NONE = "80000000"  # no point call


def word(n: int) -> str:
    return f"{n:064x}"


def encode_calls(calls: list[tuple[str, float]]) -> str:
    """26 bytes per token, sorted by address: token (20) | p_up_bps uint16 | ret_bps int32 (none)."""
    out, seen = "", set()
    for token, p in sorted(((t.lower(), p) for t, p in calls), key=lambda c: c[0]):
        if not re.fullmatch(r"0x[0-9a-f]{40}", token):
            raise ValueError(f"bad token address {token}")
        if token in seen:
            raise ValueError(f"duplicate token {token}")
        seen.add(token)
        if not 0 <= p <= 1:
            raise ValueError(f"probability must be in [0, 1], got {p} for {token}")
        bps = math.floor(p * 10000 + 0.5)  # the same rounding as JavaScript's Math.round
        out += token[2:] + f"{bps:04x}" + RET_NONE
    return out


def suffix(codes: list[str]) -> str:
    """ERC-8021 schema 0: codes (ASCII, comma joined) | length (1 byte) | 0x00 | 0x8021 x 8."""
    raw = ",".join(codes)
    if not re.fullmatch(r"[\x20-\x7e]*", raw):
        raise ValueError("builder codes must be ASCII")
    if len(raw) > 255:
        raise ValueError("builder codes too long (255 bytes at most)")
    return raw.encode("ascii").hex() + f"{len(raw):02x}" + "00" + MARKER


def calldata(window_id: int, data_hex: str, codes: list[str]) -> str:
    n = len(data_hex) // 2
    padded = data_hex + "0" * ((64 - len(data_hex) % 64) % 64)
    return ("0x" + SELECTOR + word(window_id) + word(1) + word(96) + word(n) + padded
            + (suffix(codes) if codes else ""))


# ---- fixed example for verify.py: no network, nothing sent ----
FIXTURE = {
    "window": {"id": 120261120, "label": "fixture: closed 2026-11-20", "cutoff_ms": 0, "cutoff_et": "fixture"},
    "slate": [
        {"address": "0xb20000000000000000000078ee7ce2fe4908108c", "symbol": "NVDAc"},
        {"address": "0xb2000000000000000000001e800a7f5189430cd0", "symbol": "TSLAc"},
    ],
    "probs": {"0xb20000000000000000000078ee7ce2fe4908108c": 0.62,
              "0xb2000000000000000000001e800a7f5189430cd0": 0.41},
    "builder_codes": ["bc_test123"],
    "project_codes": ["bc_akq83qpj"],
}


def split_codes(s: str | None) -> list[str]:
    return [c.strip() for c in (s or "").split(",") if c.strip()]


def pick_window(windows: list[dict], kind: str, wanted: int, now_ms: int) -> dict | None:
    kind_id = {"closed": 1, "daily": 2}.get(kind, 0)
    ok = [w for w in windows
          if w["cutoff_ms"] - now_ms > MARGIN_MS
          and (not kind_id or w["id"] // 100_000_000 == kind_id)
          and (not wanted or w["id"] == wanted)]
    return min(ok, key=lambda w: w["cutoff_ms"]) if ok else None


def fetch_form() -> dict:
    req = urllib.request.Request(FORM_URL, headers={"User-Agent": "reopen-ledger-agent", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


CDP_ACCOUNT = os.environ.get("CDP_ACCOUNT_NAME") or "reopen-ledger-agent"


def use_cdp() -> bool:
    """No private key anywhere: a Coinbase Developer Platform server account signs (pip install cdp-sdk; env
    CDP_API_KEY_ID, CDP_API_KEY_SECRET, CDP_WALLET_SECRET). It still pays its own gas, so fund its address
    (python agent.py --account) with a little ETH on Base. It sends an ordinary transaction, so the Builder Code
    suffix stays where Base reads it."""
    return not (os.environ.get("PRIVATE_KEY") or "").strip() and bool(os.environ.get("CDP_API_KEY_ID"))


async def _cdp(ledger: str | None = None, data: str | None = None) -> str:
    from cdp import CdpClient
    from cdp.evm_transaction_types import TransactionRequestEIP1559
    async with CdpClient() as cdp:
        acct = await cdp.evm.get_or_create_account(name=CDP_ACCOUNT)
        if ledger is None:
            return acct.address
        return await cdp.evm.send_transaction(address=acct.address, network="base",
                                              transaction=TransactionRequestEIP1559(to=ledger, value=0, data=data))


def send(ledger: str, data: str, window: dict) -> None:
    if use_cdp():
        import asyncio
        print(f"from     CDP server account {CDP_ACCOUNT}")
        h = asyncio.run(_cdp(ledger, data))
        h = h if h.startswith("0x") else "0x" + h
        print(f"tx       {h}")
        print(f"basescan https://basescan.org/tx/{h}")
        return
    from eth_account import Account
    from web3 import Web3

    pk = (os.environ.get("PRIVATE_KEY") or "").strip()
    if not pk:
        raise SystemExit("error: set PRIVATE_KEY, or CDP_API_KEY_ID / CDP_API_KEY_SECRET / CDP_WALLET_SECRET")
    acct = Account.from_key(pk if pk.startswith("0x") else "0x" + pk)
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    if w3.eth.chain_id != CHAIN_ID:
        raise SystemExit(f"error: RPC_URL is on chain {w3.eth.chain_id}, expected {CHAIN_ID}")
    print(f"from     {acct.address}")
    tx = {"from": acct.address, "to": Web3.to_checksum_address(ledger), "data": data, "value": 0,
          "chainId": CHAIN_ID, "nonce": w3.eth.get_transaction_count(acct.address, "pending")}
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    tip = w3.eth.max_priority_fee
    tx["maxPriorityFeePerGas"] = tip
    tx["maxFeePerGas"] = 2 * w3.eth.get_block("latest")["baseFeePerGas"] + tip
    del tx["from"]
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = "0x" + w3.eth.send_raw_transaction(raw).hex().removeprefix("0x")
    print(f"tx       {h}")
    print(f"basescan https://basescan.org/tx/{h}")
    rc = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    ts_ms = w3.eth.get_block(rc["blockNumber"])["timestamp"] * 1000
    in_time = ts_ms <= window["cutoff_ms"]
    print(f"mined    block {rc['blockNumber']}, status {'success' if rc['status'] == 1 else 'reverted'}, "
          + ("before the cutoff: it counts" if in_time else "AFTER the cutoff: it will not be scored"))
    print("The first record per wallet and window is the scored one; it shows on the board after the window resolves.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Put one probability record on the Reopen Ledger board.")
    ap.add_argument("--dry-run", action="store_true", help="print the window, probabilities and calldata; send nothing")
    ap.add_argument("--fixture", action="store_true", help="fixed example with no network (needs --dry-run)")
    ap.add_argument("--kind", choices=["any", "closed", "daily"], default="any")
    ap.add_argument("--window", type=int, default=0, help="a specific open window id")
    ap.add_argument("--due-within", type=float, default=0, metavar="HOURS",
                    help="record every open window whose cutoff falls within the next HOURS (for a once-a-day "
                         "schedule use 24: each window then gets exactly one run, holidays included)")
    ap.add_argument("--account", action="store_true", help="print the CDP server account's address (fund it with gas)")
    a = ap.parse_args(argv)
    if a.account:
        import asyncio
        print(asyncio.run(_cdp()))
        return 0

    if a.fixture:
        if not a.dry_run:
            ap.error("--fixture only works with --dry-run")
        window, slate, probs = FIXTURE["window"], FIXTURE["slate"], FIXTURE["probs"]
        ledger = EXPECTED_LEDGER
        codes = FIXTURE["builder_codes"] + FIXTURE["project_codes"]
    else:
        form = fetch_form()
        if not form.get("ledger"):
            raise SystemExit("error: the contract is not deployed yet (form.json has no ledger)")
        if form["ledger"]["chain_id"] != CHAIN_ID:
            raise SystemExit(f"error: unexpected chain id {form['ledger']['chain_id']}")
        if form["ledger"]["address"].lower() != EXPECTED_LEDGER and not os.environ.get("LEDGER_OVERRIDE"):
            raise SystemExit(f"error: form.json names ledger {form['ledger']['address']}, expected "
                             f"{EXPECTED_LEDGER} (set LEDGER_OVERRIDE=1 to accept)")
        now = int(time.time() * 1000)
        if a.due_within:
            kind_id = {"closed": 1, "daily": 2}.get(a.kind, 0)
            windows = sorted((w for w in form["windows"]
                              if MARGIN_MS < w["cutoff_ms"] - now <= a.due_within * 3_600_000
                              and (not kind_id or w["id"] // 100_000_000 == kind_id)), key=lambda w: w["cutoff_ms"])
            if not windows:
                print(f"No window has its cutoff in the next {a.due_within:g} hours. Nothing sent.")
                return 0
        else:
            w = pick_window(form["windows"], a.kind, a.window, now)
            if w is None:
                print("No window is open for records right now (or none matches --kind/--window). Nothing sent.")
                return 2
            windows = [w]
        slate = form["slate"]
        ledger = form["ledger"]["address"]
        own = split_codes(os.environ.get("BUILDER_CODES"))
        codes = own + [c for c in form.get("builder_codes") or [] if c not in own]

    on_slate = {t["address"].lower(): t for t in slate}
    if a.fixture:
        return record(window, slate, probs, codes, ledger, on_slate, a.dry_run)
    for window in windows:
        rc = record(window, slate, predict(slate, window), codes, ledger, on_slate, a.dry_run)
        if rc:
            return rc
    return 0


def record(window, slate, probs, codes, ledger, on_slate, dry_run) -> int:
    calls = []
    for token, p in probs.items():
        if token.lower() not in on_slate:
            raise SystemExit(f"error: predict() returned a token that is not on the slate: {token}")
        calls.append((token, float(p)))
    if not calls:
        raise SystemExit("error: predict() returned no probabilities")
    data = calldata(window["id"], encode_calls(calls), codes)

    print(f"window   {window['id']}  {window['label']}  (records count until {window['cutoff_et']})")
    for token, p in sorted(calls, key=lambda c: c[0].lower()):
        print(f"p        {on_slate[token.lower()]['symbol']:<8} {token.lower()}  {p:.4f}")
    print(f"codes    {','.join(codes) or '(none)'}")
    print(f"to       {ledger}")
    print(f"calldata {data}")

    if dry_run:
        print("dry run: nothing sent")
        return 0
    send(ledger, data, window)
    return 0


if __name__ == "__main__":
    sys.exit(main())
