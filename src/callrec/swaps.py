"""Swap logs of the listed pools -> a price path per pool (METHODS.md section 6).

Pool kinds (config/pools.yaml `kind`):
  cl       Uniswap v3 / Aerodrome Slipstream pool contract:
           Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1,
                uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
  v4       Uniswap v4 PoolManager, one pool per 32-byte id (topic1):
           Swap(bytes32 indexed id, address indexed sender, int128 amount0, int128 amount1,
                uint160 sqrtPriceX96, uint128 liquidity, int24 tick, uint24 fee)
  cp       Aerodrome classic volatile pool: Swap(address indexed sender, address indexed to,
           uint256 amount0In, uint256 amount1In, uint256 amount0Out, uint256 amount1Out), with the reserves
           after the swap from the Sync(uint256 reserve0, uint256 reserve1) in the same transaction.

Each swap becomes a Tick: time, block, the token's price in the pool's quote asset after the swap, the
quote amount moved (absolute), and the direction (quote out of the pool = the token-to-quote direction).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from .abi import signed, topic
from .store import row_words

TOPIC_CL_SWAP = topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
TOPIC_V4_SWAP = topic("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)")
TOPIC_CP_SWAP = topic("Swap(address,address,uint256,uint256,uint256,uint256)")
TOPIC_CP_SYNC = topic("Sync(uint256,uint256)")
Q96 = 2 ** 96


@dataclass(frozen=True)
class Pool:
    id: str                 # pool address, or "<poolmanager>:<poolId>" for v4
    kind: str               # cl | v4 | cp
    token: str              # the stock token (lowercase)
    quote: str              # the other token (lowercase)
    quote_symbol: str
    token_is_token0: bool
    dec_token: int
    dec_quote: int
    address: str            # the emitting contract (pool, or the v4 PoolManager)
    pool_id: str | None = None
    fee: float | None = None
    tick_spacing: int | None = None
    hooks: str | None = None


@dataclass(frozen=True)
class Tick:
    ts_ms: int
    block: int
    log_index: int
    price: float            # quote per token after the swap
    quote_abs: float        # quote units moved
    token_abs: float
    quote_out: bool         # True: quote left the pool (token-to-quote direction)
    tx: str
    sender: str
    recipient: str


def price_from_sqrt(p: Pool, sqrt_x96: int) -> float:
    raw = (sqrt_x96 / Q96) ** 2                 # token1 per token0, raw units
    if p.token_is_token0:                       # quote per token = token1/token0
        return raw * 10 ** (p.dec_token - p.dec_quote)
    return (1 / raw) * 10 ** (p.dec_token - p.dec_quote) if raw else 0.0


def decode_cl(p: Pool, row: dict) -> Tick | None:
    w = row_words(row)
    a0, a1 = signed(w[0]), signed(w[1])
    amt_token, amt_quote = (a0, a1) if p.token_is_token0 else (a1, a0)
    return Tick(row["ts_ms"], row["block"], row["log_index"], price_from_sqrt(p, w[2]),
                abs(amt_quote) / 10 ** p.dec_quote, abs(amt_token) / 10 ** p.dec_token, amt_quote < 0,
                row["tx"], "0x" + row["topics"][1][-40:], "0x" + row["topics"][2][-40:])


def decode_v4(p: Pool, row: dict) -> Tick | None:
    if row["topics"][1].lower() != (p.pool_id or "").lower():
        return None
    w = row_words(row)
    # v4 amounts are from the swapper's side: negative = paid into the pool
    a0, a1 = signed(w[0], 128), signed(w[1], 128)
    amt_token, amt_quote = (a0, a1) if p.token_is_token0 else (a1, a0)
    return Tick(row["ts_ms"], row["block"], row["log_index"], price_from_sqrt(p, w[2]),
                abs(amt_quote) / 10 ** p.dec_quote, abs(amt_token) / 10 ** p.dec_token, amt_quote > 0,
                row["tx"], "0x" + row["topics"][2][-40:], "")


def decode_cp(p: Pool, swap: dict, sync: dict | None) -> Tick | None:
    w = row_words(swap)
    in0, in1, out0, out1 = w[0], w[1], w[2], w[3]
    if p.token_is_token0:
        tok_in, tok_out, q_in, q_out = in0, out0, in1, out1
    else:
        tok_in, tok_out, q_in, q_out = in1, out1, in0, out0
    price = None
    if sync is not None:
        r = row_words(sync)
        r_tok, r_q = (r[0], r[1]) if p.token_is_token0 else (r[1], r[0])
        if r_tok:
            price = (r_q / 10 ** p.dec_quote) / (r_tok / 10 ** p.dec_token)
    if price is None:
        return None
    return Tick(swap["ts_ms"], swap["block"], swap["log_index"], price,
                max(q_in, q_out) / 10 ** p.dec_quote, max(tok_in, tok_out) / 10 ** p.dec_token, q_out > 0,
                swap["tx"], "0x" + swap["topics"][1][-40:], "0x" + swap["topics"][2][-40:])


def ticks_for(p: Pool, rows: list[dict]) -> list[Tick]:
    """rows: raw-store rows emitted by p.address, in chain order."""
    out: list[Tick] = []
    if p.kind == "cl":
        for r in rows:
            if r["address"] == p.address and r["topics"] and r["topics"][0] == TOPIC_CL_SWAP:
                out.append(decode_cl(p, r))
    elif p.kind == "v4":
        for r in rows:
            if r["address"] == p.address and r["topics"] and r["topics"][0] == TOPIC_V4_SWAP:
                t = decode_v4(p, r)
                if t:
                    out.append(t)
    elif p.kind == "cp":
        last_sync: dict | None = None
        pending: list[dict] = []
        for r in rows:
            if r["address"] != p.address or not r["topics"]:
                continue
            if r["topics"][0] == TOPIC_CP_SYNC:
                last_sync = r
                for s in pending:
                    if s["tx"] == r["tx"]:
                        t = decode_cp(p, s, r)
                        if t:
                            out.append(t)
                pending = []
            elif r["topics"][0] == TOPIC_CP_SWAP:
                # Solidly-style pools emit Sync before Swap in the same transaction
                if last_sync is not None and last_sync["tx"] == r["tx"]:
                    t = decode_cp(p, r, last_sync)
                    if t:
                        out.append(t)
                else:
                    pending.append(r)
    return [t for t in out if t is not None and t.price > 0]


class Path:
    """A pool's price path, piecewise constant between swaps, held as compact arrays (millions of swaps fit
    in memory); Tick objects are made on demand. Build from Ticks (tests) or with PathBuilder (streaming)."""

    def __init__(self, ticks: list[Tick] | None = None):
        from array import array
        self._ts, self.block, self.li = array("q"), array("q"), array("q")
        self.price, self.qabs, self.tabs = array("d"), array("d"), array("d")
        self.qout, self.rid = array("b"), array("q")
        self.recips: list[str] = []
        if ticks:
            ids: dict[str, int] = {}
            for t in sorted(ticks, key=lambda t: (t.block, t.log_index)):
                rid = ids.setdefault(t.recipient, len(ids))
                self._push(t.ts_ms, t.block, t.log_index, t.price, t.quote_abs, t.token_abs, t.quote_out, rid)
            self.recips = [None] * len(ids)
            for k, v in ids.items():
                self.recips[v] = k

    def _push(self, ts, block, li, price, qabs, tabs, qout, rid):
        self._ts.append(ts)
        self.block.append(block)
        self.li.append(li)
        self.price.append(price)
        self.qabs.append(qabs)
        self.tabs.append(tabs)
        self.qout.append(1 if qout else 0)
        self.rid.append(rid)

    def __len__(self) -> int:
        return len(self._ts)

    def tick(self, i: int) -> Tick:
        return Tick(self._ts[i], self.block[i], self.li[i], self.price[i], self.qabs[i], self.tabs[i],
                    bool(self.qout[i]), "", "", self.recips[self.rid[i]] if self.recips else "")

    @property
    def ticks(self) -> list[Tick]:
        return [self.tick(i) for i in range(len(self))]

    def index_range(self, a: int, b: int) -> tuple[int, int]:
        return bisect.bisect_left(self._ts, a), bisect.bisect_right(self._ts, b)

    def at(self, ts_ms: int) -> Tick | None:
        i = bisect.bisect_right(self._ts, ts_ms) - 1
        return self.tick(i) if i >= 0 else None

    def between(self, a: int, b: int) -> list[Tick]:
        i, j = self.index_range(a, b)
        return [self.tick(k) for k in range(i, j)]

    def count_between(self, a: int, b: int) -> int:
        i, j = self.index_range(a, b)
        return j - i

    def twap(self, a: int, b: int) -> float | None:
        """Time-weighted price over [a, b]; None if no price is known at or before a or inside."""
        if b <= a:
            return None
        k = bisect.bisect_right(self._ts, a) - 1
        if k < 0:
            i, j = self.index_range(a, b)
            if i >= j:
                return None
            k, a = i, self._ts[i]
            if b <= a:
                return self.price[k]
        acc, cur, t0 = 0.0, self.price[k], a
        i, j = self.index_range(a + 1, b)
        for m in range(i, j):
            acc += cur * (self._ts[m] - t0)
            cur, t0 = self.price[m], self._ts[m]
        acc += cur * (b - t0)
        return acc / (b - a)


class PathBuilder:
    """Streaming decode: append rows in chain order, then finish() -> Path. Recipients are interned in a
    table shared by all builders made with the same `ids` dict."""

    def __init__(self, pool: Pool, ids: dict[str, int], table: list[str]):
        self.pool, self.ids, self.table = pool, ids, table
        self.path = Path()
        self.path.recips = table
        self._last_sync: dict | None = None

    def _rid(self, addr: str) -> int:
        r = self.ids.get(addr)
        if r is None:
            r = len(self.table)
            self.ids[addr] = r
            self.table.append(addr)
        return r

    def add(self, row: dict) -> None:
        p, t = self.pool, row["topics"]
        if not t:
            return
        if p.kind == "cl" and t[0] == TOPIC_CL_SWAP:
            k = decode_cl(p, row)
        elif p.kind == "v4" and t[0] == TOPIC_V4_SWAP:
            k = decode_v4(p, row)
        elif p.kind == "cp" and t[0] == TOPIC_CP_SYNC:
            self._last_sync = row
            return
        elif p.kind == "cp" and t[0] == TOPIC_CP_SWAP:
            s = self._last_sync if (self._last_sync and self._last_sync["tx"] == row["tx"]) else None
            k = decode_cp(p, row, s)
        else:
            return
        if k is None or k.price <= 0:
            return
        self.path._push(k.ts_ms, k.block, k.log_index, k.price, k.quote_abs, k.token_abs, k.quote_out,
                        self._rid(k.recipient))

    def finish(self) -> Path:
        return self.path
