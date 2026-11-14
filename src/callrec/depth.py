"""Downward depth from pool state (METHODS.md section 8): how much of the quote asset a pool pays out as the
token's price moves down, assuming liquidity providers do not move.

Concentrated-liquidity pools (Aerodrome Slipstream, Uniswap v3, Uniswap v4): walk initialized ticks in the
direction the token's price falls, summing the quote amount out per range:
  quote is token0:  token price falls  <=> sqrtP (token1 per token0) rises;  dq = L * (1/sa - 1/sb)
  quote is token1:  token price falls  <=> sqrtP falls;                       dq = L * (sb - sa)
with sa < sb the range's sqrt prices (real, not Q96) in raw units. Crossing a tick upward adds its
liquidityNet; downward subtracts it.
Constant-product pools (Aerodrome classic volatile): with quote reserve x and token reserve y,
x = sqrt(k * P) so the quote out from P0 down to P1 is sqrt(k) * (sqrt(P0) - sqrt(P1)) (raw units, P in
quote per token).

Every function here is pure; readers that fetch tick state live in pools.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Q96 = 2 ** 96
TICK_BASE = 1.0001


def sqrt_at_tick(tick: int) -> float:
    return TICK_BASE ** (tick / 2)


@dataclass
class ClState:
    """A concentrated-liquidity pool at one block."""
    sqrt_price_x96: int
    tick: int
    liquidity: int
    tick_spacing: int
    ticks: dict[int, int] = field(default_factory=dict)   # initialized tick -> liquidityNet
    quote_is_token0: bool = True
    dec_token: int = 8
    dec_quote: int = 6

    def token_price(self) -> float:
        """Quote per token (decimal-adjusted)."""
        p = (self.sqrt_price_x96 / Q96) ** 2   # token1 per token0, raw
        if self.quote_is_token0:
            # token1 = stock: stock raw per quote raw -> quote per stock
            return (1 / p) * 10 ** (self.dec_token - self.dec_quote)
        return p * 10 ** (self.dec_token - self.dec_quote)


def _raw_sqrt_for_token_price(st: ClState, token_price: float) -> float:
    """Real sqrt of the raw pool price (token1 per token0) at a given decimal token price."""
    if st.quote_is_token0:
        p_raw = 10 ** (st.dec_token - st.dec_quote) / token_price
    else:
        p_raw = token_price / 10 ** (st.dec_token - st.dec_quote)
    return math.sqrt(p_raw)


def cl_quote_out(st: ClState, from_price: float, to_price: float) -> float:
    """Quote paid out (decimal units) as the token price moves from `from_price` down to `to_price`,
    starting from the pool's current state. `from_price` may be below the current price (a shocked level):
    the walk starts at the current state and counts only the part below `from_price`."""
    if to_price >= from_price:
        return 0.0
    cur = st.sqrt_price_x96 / Q96
    s_from = _raw_sqrt_for_token_price(st, from_price)
    s_to = _raw_sqrt_for_token_price(st, to_price)
    L = st.liquidity
    total_raw = 0.0
    if st.quote_is_token0:
        # price of token falls as sqrt rises; walk ticks upward from the current tick
        s = cur
        upper_ticks = sorted(t for t in st.ticks if t > st.tick)
        boundaries = [(sqrt_at_tick(t), t) for t in upper_ticks] + [(float("inf"), None)]
        for sb_tick, t in boundaries:
            seg_hi = min(sb_tick, s_to)
            lo = max(s, s_from)
            if seg_hi > lo and L > 0:
                total_raw += L * (1 / lo - 1 / seg_hi)
            if sb_tick >= s_to or t is None:
                break
            s = sb_tick
            L += st.ticks[t]
    else:
        # price of token falls as sqrt falls; walk ticks downward
        s = cur
        lower_ticks = sorted((t for t in st.ticks if t <= st.tick), reverse=True)
        boundaries = [(sqrt_at_tick(t), t) for t in lower_ticks] + [(0.0, None)]
        for sa_tick, t in boundaries:
            seg_lo = max(sa_tick, s_to)
            hi = min(s, s_from)
            if hi > seg_lo and L > 0:
                total_raw += L * (hi - seg_lo)
            if sa_tick <= s_to or t is None:
                break
            s = sa_tick
            L -= st.ticks[t]
    return total_raw / 10 ** st.dec_quote


@dataclass
class CpState:
    """A constant-product pool: reserves in raw units."""
    reserve_quote: int
    reserve_token: int
    dec_token: int = 8
    dec_quote: int = 6

    def token_price(self) -> float:
        return (self.reserve_quote / 10 ** self.dec_quote) / (self.reserve_token / 10 ** self.dec_token)


def cp_quote_out(st: CpState, from_price: float, to_price: float) -> float:
    if to_price >= from_price:
        return 0.0
    x = st.reserve_quote / 10 ** st.dec_quote
    y = st.reserve_token / 10 ** st.dec_token
    k = x * y
    p0 = min(from_price, st.token_price())
    if to_price >= p0:
        return 0.0
    return math.sqrt(k) * (math.sqrt(p0) - math.sqrt(to_price))


def quote_out(st, from_price: float, to_price: float) -> float:
    return cl_quote_out(st, from_price, to_price) if isinstance(st, ClState) else cp_quote_out(st, from_price, to_price)


def swap_token_for_quote(st, notional_quote: float, fee: float = 0.0, steps: int = 60) -> dict:
    """Price impact of swapping tokens worth `notional_quote` (at the current price) into the quote asset:
    bisect the price level whose quote-out equals the notional. Returns the end price, the average
    execution price, and the impact in basis points (before the pool fee, which is reported apart)."""
    p0 = st.token_price()
    lo, hi = 0.0, p0
    if quote_out(st, p0, 1e-12 * p0) < notional_quote:
        return {"filled": False, "available_quote": quote_out(st, p0, 1e-12 * p0)}
    for _ in range(steps):
        mid = (lo + hi) / 2
        if quote_out(st, p0, mid) >= notional_quote:
            lo = mid
        else:
            hi = mid
    end = (lo + hi) / 2
    # token amount needed: integrate via the inverse: tokens in = quote_out / average price; average price
    # from the quote-out at the end price and the token-in, computed with the same walk on the token side
    tokens_in = _token_in(st, p0, end)
    avg = notional_quote / tokens_in if tokens_in > 0 else p0
    return {"filled": True, "end_price": end, "avg_price": avg, "impact_bps": (1 - avg / p0) * 1e4,
            "end_move_bps": (1 - end / p0) * 1e4, "fee_bps": fee * 1e4}


def _token_in(st, from_price: float, to_price: float) -> float:
    """Tokens (decimal) taken in as the price moves from from_price down to to_price."""
    if isinstance(st, CpState):
        x = st.reserve_quote / 10 ** st.dec_quote
        y = st.reserve_token / 10 ** st.dec_token
        k = x * y
        return math.sqrt(k) * (1 / math.sqrt(to_price) - 1 / math.sqrt(from_price))
    # CL: token amount = L * (sb - sa) when token is token1 (quote token0), L * (1/sa - 1/sb) otherwise
    cur = st.sqrt_price_x96 / Q96
    s_to = _raw_sqrt_for_token_price(st, to_price)
    L = st.liquidity
    total = 0.0
    if st.quote_is_token0:
        s = cur
        for t in sorted(x for x in st.ticks if x > st.tick) + [None]:
            sb = sqrt_at_tick(t) if t is not None else float("inf")
            hi = min(sb, s_to)
            if hi > s and L > 0:
                total += L * (hi - s)
            if t is None or sb >= s_to:
                break
            s = sb
            L += st.ticks[t]
    else:
        s = cur
        for t in sorted((x for x in st.ticks if x <= st.tick), reverse=True) + [None]:
            sa = sqrt_at_tick(t) if t is not None else 0.0
            lo = max(sa, s_to)
            if s > lo and L > 0:
                total += L * (1 / lo - 1 / s)
            if t is None or sa <= s_to:
                break
            s = sa
            L -= st.ticks[t]
    return total / 10 ** st.dec_token


def ladder(states: list[tuple[object, float]], ref_price: float) -> dict:
    """Depth across pools for one token. states: (pool state, quote-to-USD factor). Returns USD amounts:
    move_1pct / move_2pct: quote paid out from the current price down 1% / 2% (each pool from its own price)
    absorb_5pct_below[s]: quote paid out from ref*(1-s) down to ref*(1-s)*0.95, for s in 5, 10, 20%."""
    out = {"move_1pct_usd": 0.0, "move_2pct_usd": 0.0, "absorb_5pct_below_usd": {}}
    for st, usd in states:
        p = st.token_price()
        out["move_1pct_usd"] += quote_out(st, p, p * 0.99) * usd
        out["move_2pct_usd"] += quote_out(st, p, p * 0.98) * usd
    for s in (0.05, 0.10, 0.20):
        a = ref_price * (1 - s)
        out["absorb_5pct_below_usd"][f"{int(s * 100)}"] = sum(
            quote_out(st, min(a, st.token_price()), a * 0.95) * usd for st, usd in states)
    return out
