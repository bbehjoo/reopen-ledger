"""The official token registry: every Coinbase-issued B20 stock token, from Coinbase's published list,
checked on chain.

`build_registry` fetches every page of the Tokenized Stocks API and, for each token, reads `symbol()`,
`decimals()` and `uiMultiplier()` at the latest block. A row whose chain values differ from the API's gets
`chain_matches_api: false` (with both values); nothing is dropped. The snapshot is config/tokens.json,
stamped with its fetch time and source URL, and the site and the TypeScript client read it.

A lookalike is a token seen in DEX Swap logs whose symbol matches an official token's symbol but whose
address is not on the list (flag `R1_lookalike_symbol`, METHODS.md §6).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import httpx

from . import config
from .abi import decode_string, decode_uint, selector
from .rpc import USER_AGENT, RpcError

API = "https://api.coinbase.com/v1/tokenized-stocks"


def fetch_api(client: httpx.Client | None = None, max_pages: int = 50) -> list[dict]:
    own = client is None
    client = client or httpx.Client(timeout=30, headers={"user-agent": USER_AGENT})
    rows, token = [], None
    try:
        for _ in range(max_pages):
            params = {"page_token": token} if token else None
            r = client.get(API, params=params)
            r.raise_for_status()
            j = r.json()
            rows += j.get("tokens", [])
            token = j.get("next_page_token")
            if not token:
                break
            time.sleep(0.3)
    finally:
        if own:
            client.close()
    seen, out = set(), []
    for t in rows:
        a = t["contract_address"].lower()
        if a not in seen:
            seen.add(a)
            out.append(t)
    return out


def chain_check(rpc, tokens: list[dict]) -> list[dict]:
    calls = []
    for t in tokens:
        a = t["contract_address"]
        calls += [("eth_call", [{"to": a, "data": selector("symbol()")}, "latest"]),
                  ("eth_call", [{"to": a, "data": selector("decimals()")}, "latest"]),
                  ("eth_call", [{"to": a, "data": selector("uiMultiplier()")}, "latest"])]
    res = rpc.batch(calls)
    out = []
    for i, t in enumerate(tokens):
        sym, dec, mult = res[3 * i: 3 * i + 3]
        row = {
            "address": t["contract_address"].lower(),
            "symbol": t["symbol"],
            "name": t.get("name"),
            "isin": t.get("isin"),
            "decimals": t.get("decimals"),
            "api_multiplier": t.get("multiplier"),
            "api_nav_price": t.get("nav_price"),
            "api_nav_price_updated_at": t.get("nav_price_updated_at"),
        }
        chain = {}
        chain["symbol"] = None if isinstance(sym, RpcError) or sym is None else decode_string(sym)
        chain["decimals"] = None if isinstance(dec, RpcError) or dec is None else decode_uint(dec)
        chain["ui_multiplier_wad"] = None if isinstance(mult, RpcError) or mult is None else str(decode_uint(mult))
        row["chain"] = chain
        row["chain_matches_api"] = chain["symbol"] == t["symbol"] and chain["decimals"] == t.get("decimals")
        out.append(row)
    return out


def build_registry(rpc) -> dict:
    tokens = fetch_api()
    rows = chain_check(rpc, tokens)
    rows.sort(key=lambda r: r["symbol"])
    return {
        "schema": "callrec-tokens/v1",
        "source": API,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(rows),
        "tokens": rows,
    }


def load() -> dict:
    return config.load_json("tokens.json")


def by_address() -> dict[str, dict]:
    return {t["address"]: t for t in load()["tokens"]}


def by_symbol() -> dict[str, dict]:
    return {t["symbol"]: t for t in load()["tokens"]}


def write(doc: dict) -> None:
    p = config.config_dir() / "tokens.json"
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
