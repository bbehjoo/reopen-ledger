"""Depth math: a full-range concentrated position equals a constant-product pool; tick crossings add
liquidityNet; swap impact is consistent with quote-out."""

import math

import pytest

from callrec.depth import ClState, CpState, Q96, cl_quote_out, cp_quote_out, ladder, swap_token_for_quote

MIN_T, MAX_T = -887200, 887200


def cl_from_price(token_price, L, quote_is_token0=True, ticks=None):
    # quote token0 (USDC, 6), token1 = stock (8): raw price token1/token0 = 10**2 / token_price
    p_raw = 10 ** 2 / token_price if quote_is_token0 else token_price / 10 ** 2
    sq = math.sqrt(p_raw)
    tick = math.floor(math.log(p_raw) / math.log(1.0001))
    t = {MIN_T: L, MAX_T: -L} if ticks is None else ticks
    return ClState(int(sq * Q96), tick, L, 200, t, quote_is_token0)


@pytest.mark.parametrize("quote_is_token0", [True, False])
def test_full_range_equals_constant_product(quote_is_token0):
    price, L = 200.0, 10 ** 12
    st = cl_from_price(price, L, quote_is_token0)
    sq = math.sqrt(10 ** 2 / price) if quote_is_token0 else math.sqrt(price / 10 ** 2)
    x_raw, y_raw = (L / sq, L * sq) if quote_is_token0 else (L * sq, L / sq)  # quote raw, token raw
    cp = CpState(int(x_raw), int(y_raw))
    assert cp.token_price() == pytest.approx(price, rel=1e-6)
    assert st.token_price() == pytest.approx(price, rel=1e-9)
    for to in (198.0, 190.0, 150.0):
        assert cl_quote_out(st, price, to) == pytest.approx(cp_quote_out(cp, price, to), rel=1e-6)


def test_crossing_a_tick_adds_liquidity_net():
    price, L = 200.0, 10 ** 12
    p_raw = 10 ** 2 / price
    tick = math.floor(math.log(p_raw) / math.log(1.0001))
    # a second position starting 500 ticks above the current tick (token price about 5% lower)
    t2 = tick + 500
    st1 = cl_from_price(price, L)
    st2 = cl_from_price(price, L, ticks={MIN_T: L, MAX_T: -L, t2: L, t2 + 2000: -L})
    hi = cl_quote_out(st1, price, 160.0)
    hi2 = cl_quote_out(st2, price, 160.0)
    assert hi2 > hi
    # above the second range's start (less than ~5% move) the two pools are the same
    assert cl_quote_out(st2, price, 195.0) == pytest.approx(cl_quote_out(st1, price, 195.0), rel=1e-9)


def test_shocked_start_counts_only_below():
    price, L = 200.0, 10 ** 12
    st = cl_from_price(price, L)
    whole = cl_quote_out(st, price, 171.0)
    part = cl_quote_out(st, 180.0, 171.0)
    upper = cl_quote_out(st, price, 180.0)
    assert part == pytest.approx(whole - upper, rel=1e-9)


def test_swap_impact_and_ladder():
    price, L = 200.0, 10 ** 12
    st = cl_from_price(price, L)
    small = swap_token_for_quote(st, 1_000.0)
    big = swap_token_for_quote(st, 100_000.0)
    assert small["filled"] and big["filled"]
    assert 0 < small["impact_bps"] < big["impact_bps"]
    lad = ladder([(st, 1.0)], price)
    assert lad["move_2pct_usd"] > lad["move_1pct_usd"] > 0
    assert set(lad["absorb_5pct_below_usd"]) == {"5", "10", "20"}
