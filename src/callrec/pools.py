"""Listed pools (config/pools.yaml) -> swaps.Pool objects and price paths from the raw `swaps` stream.

config/pools.yaml lists each pool with its protocol, address (or v4 PoolManager and pool id), tokens and
decimals, each verified on chain against its factory. Only pools whose `token` is official are used.
"""

from __future__ import annotations

from collections import defaultdict
from functools import cache

import yaml

from . import config, feeds, store
from .swaps import TOPIC_CL_SWAP, TOPIC_CP_SWAP, TOPIC_CP_SYNC, TOPIC_V4_SWAP, Pool
from .tape import PoolPath

STREAM = "swaps"
KIND_OF = {"aerodrome-slipstream": "cl", "uniswap-v3": "cl", "uniswap-v4": "v4", "aerodrome-classic": "cp"}


@cache
def raw_config() -> dict:
    p = config.config_dir() / "pools.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


PAIR_CLASSES = ("USDC",)   # pools priced in USD without another feed; WETH/ETH pairs are not used yet


def _measured_tokens() -> set[str]:
    """Official tokens with a 24/5 reference feed: the only tokens measured."""
    from . import registry
    official = set(registry.by_address())
    return {f["token"] for f in feeds.load() if f.get("token") and f["kind"] == "24/5" and f["token"] in official}


def load_pools() -> list[Pool]:
    """Normalised pools: official measured tokens, supported protocols, USDC pairs (METHODS.md section 6)."""
    measured = _measured_tokens()
    out = []
    for e in raw_config().get("pools", []) or []:
        if (e.get("stock_token") or "").lower() not in measured:
            continue
        if (e.get("pair_token") or {}).get("class") not in PAIR_CLASSES:
            continue
        p = _pool(e)
        if p is not None:
            out.append(p)
    return out


def _pool(e: dict) -> Pool | None:
    kind = KIND_OF.get(e.get("protocol"))
    if kind is None or e.get("exclude"):
        return None
    t0, t1 = e["token0"]["address"].lower(), e["token1"]["address"].lower()
    stock = e["stock_token"].lower()
    token_is_token0 = stock == t0
    quote = t1 if token_is_token0 else t0
    qd = e["token1"] if token_is_token0 else e["token0"]
    td = e["token0"] if token_is_token0 else e["token1"]
    if kind == "v4":
        address = e["pool_manager"].lower()
        pid = e["pool_id"].lower()
        ident = f"{address}:{pid}"
    else:
        address = e["address"].lower()
        pid = None
        ident = address
    return Pool(ident, kind, stock, quote, qd.get("symbol", "?"), token_is_token0, int(td["decimals"]),
                int(qd["decimals"]), address, pid, e.get("fee"), e.get("tick_spacing"), (e.get("hooks") or None))


def stream_specs() -> list[dict]:
    """`swaps`: pool contracts (concentrated and classic); `swaps_v4`: the PoolManager filtered by pool id."""
    pools = load_pools()
    pair = sorted({p.address for p in pools if p.kind in ("cl", "cp")})
    v4 = [p for p in pools if p.kind == "v4"]
    out = []
    if pair:
        out.append({"stream": STREAM, "addresses": pair, "topics": [[TOPIC_CL_SWAP, TOPIC_CP_SWAP, TOPIC_CP_SYNC]]})
    if v4:
        out.append({"stream": "swaps_v4", "addresses": sorted({p.address for p in v4}),
                    "topics": [[TOPIC_V4_SWAP], sorted({p.pool_id for p in v4})]})
    return out


def usd_factor(quote: str, as_of_ms: int):
    """USD per unit of a pool's quote asset at a time: 1 for USDC, the ETH/USD feed for WETH."""
    chain = config.chain()
    if quote == chain["usdc"].lower():
        return lambda ts: 1.0
    if quote == chain["weth"].lower():
        eth = _eth_series(as_of_ms)
        if eth is None:
            return lambda ts: None

        def f(ts, s=eth):
            u = s.at(ts)
            return s.price(u) if u else None
        return f
    return lambda ts: None


@cache
def _eth_series(as_of_ms: int):
    cfg = [{"proxy": "eth", "decimals": 8, "chain": {"phase_aggregators": [
        {"aggregator": a.lower()} for a in config.chain().get("eth_usd_aggregators", [])]}}]
    if not cfg[0]["chain"]["phase_aggregators"]:
        return None
    rows = [x for x in store.read("ethusd") if x["ts_ms"] <= as_of_ms]
    return feeds.load_series(cfg, rows)["eth"]


def load_paths(as_of_ms: int) -> dict[str, list[PoolPath]]:
    pools = load_pools()
    if not pools:
        return {}
    from .swaps import PathBuilder
    ids: dict[str, int] = {}
    table: list[str] = []
    builders = {p.id: PathBuilder(p, ids, table) for p in pools}
    by_addr = defaultdict(list)          # emitting contract -> builders (v4: one per pool id, filtered there)
    for p in pools:
        by_addr[p.address].append(builders[p.id])
    for stream in (STREAM, "swaps_v4"):
        for row in store.read(stream, to_ms=as_of_ms, packed=True):
            for b in by_addr.get(row["address"], ()):
                b.add(row)
    out: dict[str, list[PoolPath]] = defaultdict(list)
    for p in pools:
        out[p.token].append(PoolPath(p.id, builders[p.id].finish(), usd_factor(p.quote, as_of_ms)))
    return dict(out)
