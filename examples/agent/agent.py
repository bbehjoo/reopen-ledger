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

Env: PRIVATE_KEY (hex, the wallet that signs), BUILDER_CODES (yours, comma separated, optional),
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
# The default below says 0.5 for everything, which scores exactly like a coin flip.
# =====================================================================================================
def predict(slate: list[dict], window: dict) -> dict[str, float]:
    return {t["address"]: 0.5 for t in slate}


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


def send(ledger: str, data: str, window: dict) -> None:
    from eth_account import Account
    from web3 import Web3

    pk = (os.environ.get("PRIVATE_KEY") or "").strip()
    if not pk:
        raise SystemExit("error: PRIVATE_KEY is not set")
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
    a = ap.parse_args(argv)

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
        window = pick_window(form["windows"], a.kind, a.window, int(time.time() * 1000))
        if window is None:
            print("No window is open for records right now (or none matches --kind/--window). Nothing sent.")
            return 2
        slate = form["slate"]
        ledger = form["ledger"]["address"]
        own = split_codes(os.environ.get("BUILDER_CODES"))
        codes = own + [c for c in form.get("builder_codes") or [] if c not in own]
        probs = predict(slate, window)

    on_slate = {t["address"].lower(): t for t in slate}
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

    if a.dry_run:
        print("dry run: nothing sent")
        return 0
    send(ledger, data, window)
    return 0


if __name__ == "__main__":
    sys.exit(main())
