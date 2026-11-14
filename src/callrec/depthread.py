"""Pool state at a block, for the depth engine (depth.py). Read-only eth_calls.

  cl  (Slipstream, Uniswap v3)  slot0(), liquidity(), tickSpacing(), tickBitmap(int16), ticks(int24)
                                (liquidityNet is the second word of ticks() in both)
  v4  (Uniswap v4 StateView)    getSlot0(bytes32), getLiquidity(bytes32), getTickBitmap(bytes32,int16),
                                getTickLiquidity(bytes32,int24) -> (liquidityGross, liquidityNet)
  cp  (Aerodrome classic)       getReserves()

The tick walk reads initialized ticks from the current tick to the tick where the token price is
`floor_factor` of the current price (default 0.70: below the 20% shock and a further 5%).
Snapshots go to data/raw/snapshots/depth/<block>.json, the replay input of every depth number.
"""

from __future__ import annotations

import json
import math

from . import config
from .abi import enc_uint, selector, signed, words
from .depth import ClState, CpState

TICK_BASE = 1.0001


def _w(rpc, to: str, data: str, block: int) -> list[int]:
    return words(rpc.eth_call(to, data, block))


def _tick_range(tick: int, spacing: int, token_is_token0: bool, floor_factor: float) -> tuple[int, int]:
    span = int(math.log(1 / floor_factor) / math.log(TICK_BASE)) + spacing
    # the token's price falls as the raw price (token1/token0) rises when the token is token1
    return (tick, tick + span) if not token_is_token0 else (tick - span, tick)


def _bitmap_ticks(read_word, tick_lo: int, tick_hi: int, spacing: int) -> list[int]:
    out = []
    c_lo, c_hi = math.floor(tick_lo / spacing), math.floor(tick_hi / spacing)
    for wpos in range(c_lo >> 8, (c_hi >> 8) + 1):
        bm = read_word(wpos)
        if not bm:
            continue
        for bit in range(256):
            if bm >> bit & 1:
                t = ((wpos << 8) + bit) * spacing
                if tick_lo <= t <= tick_hi:
                    out.append(t)
    return out


def read_cl(rpc, pool, block: int, floor_factor: float = 0.70) -> tuple[ClState, dict]:
    a = pool.address
    s0 = _w(rpc, a, selector("slot0()"), block)
    sqrt_p, tick = s0[0], signed(s0[1], 24)
    liq = _w(rpc, a, selector("liquidity()"), block)[0]
    spacing = signed(_w(rpc, a, selector("tickSpacing()"), block)[0], 24)
    lo, hi = _tick_range(tick, spacing, pool.token_is_token0, floor_factor)

    def word(wpos):
        return _w(rpc, a, selector("tickBitmap(int16)") + enc_uint(wpos), block)[0]

    ticks = _bitmap_ticks(word, lo, hi, spacing)
    res = rpc.batch([("eth_call", [{"to": a, "data": selector("ticks(int24)") + enc_uint(t)}, hex(block)]) for t in ticks])
    nets = {t: signed(words(r)[1], 128) for t, r in zip(ticks, res, strict=True) if isinstance(r, str)}
    st = ClState(sqrt_p, tick, liq, spacing, nets, quote_is_token0=not pool.token_is_token0,
                 dec_token=pool.dec_token, dec_quote=pool.dec_quote)
    raw = {"kind": "cl", "sqrt_price_x96": str(sqrt_p), "tick": tick, "liquidity": str(liq), "tick_spacing": spacing,
           "ticks": {str(t): str(n) for t, n in sorted(nets.items())}}
    return st, raw


def read_v4(rpc, pool, state_view: str, block: int, floor_factor: float = 0.70) -> tuple[ClState, dict]:
    pid = pool.pool_id.removeprefix("0x").rjust(64, "0")
    s0 = _w(rpc, state_view, selector("getSlot0(bytes32)") + pid, block)
    sqrt_p, tick = s0[0], signed(s0[1], 24)
    liq = _w(rpc, state_view, selector("getLiquidity(bytes32)") + pid, block)[0]
    spacing = int(pool.tick_spacing)
    lo, hi = _tick_range(tick, spacing, pool.token_is_token0, floor_factor)

    def word(wpos):
        return _w(rpc, state_view, selector("getTickBitmap(bytes32,int16)") + pid + enc_uint(wpos), block)[0]

    ticks = _bitmap_ticks(word, lo, hi, spacing)
    res = rpc.batch([("eth_call", [{"to": state_view, "data": selector("getTickLiquidity(bytes32,int24)") + pid + enc_uint(t)},
                                   hex(block)]) for t in ticks])
    nets = {t: signed(words(r)[1], 128) for t, r in zip(ticks, res, strict=True) if isinstance(r, str)}
    st = ClState(sqrt_p, tick, liq, spacing, nets, quote_is_token0=not pool.token_is_token0,
                 dec_token=pool.dec_token, dec_quote=pool.dec_quote)
    raw = {"kind": "v4", "sqrt_price_x96": str(sqrt_p), "tick": tick, "liquidity": str(liq), "tick_spacing": spacing,
           "ticks": {str(t): str(n) for t, n in sorted(nets.items())}}
    return st, raw


def read_cp(rpc, pool, block: int) -> tuple[CpState, dict]:
    r = _w(rpc, pool.address, selector("getReserves()"), block)
    r_tok, r_q = (r[0], r[1]) if pool.token_is_token0 else (r[1], r[0])
    st = CpState(r_q, r_tok, pool.dec_token, pool.dec_quote)
    return st, {"kind": "cp", "reserve_quote": str(r_q), "reserve_token": str(r_tok)}


def state_from_raw(pool, raw: dict):
    if raw["kind"] == "cp":
        return CpState(int(raw["reserve_quote"]), int(raw["reserve_token"]), pool.dec_token, pool.dec_quote)
    return ClState(int(raw["sqrt_price_x96"]), int(raw["tick"]), int(raw["liquidity"]), int(raw["tick_spacing"]),
                   {int(t): int(n) for t, n in raw["ticks"].items()}, quote_is_token0=not pool.token_is_token0,
                   dec_token=pool.dec_token, dec_quote=pool.dec_quote)


def snapshot_dir():
    return config.data_dir() / "raw" / "snapshots" / "depth"


def save(doc: dict) -> None:
    d = snapshot_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc['block']}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                            newline="\n")


def snapshots(at_or_before_ms: int | None = None) -> list[dict]:
    d = snapshot_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda p: int(p.stem)):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if at_or_before_ms is None or doc["ts_ms"] <= at_or_before_ms:
            out.append(doc)
    return out
