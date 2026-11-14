from callrec import swaps
from callrec.swaps import Pool, Path, Tick, price_from_sqrt

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TOK = "0xb20000000000000000000078ee7ce2fe4908108c"


def pool(kind="cl", token_is_token0=False):
    return Pool("0xpool", kind, TOK, USDC, "USDC", token_is_token0, 8, 6, "0xpool", None)


def w(v, bits=256):
    return f"{v % (1 << bits):064x}"


def test_price_from_sqrt_when_quote_is_token0():
    # USDC (token0, 6 dec) / stock (token1, 8 dec) at $200: raw token1 per token0 = 1e8/(200*1e6) = 0.5
    import math
    sq = int(math.sqrt(0.5) * swaps.Q96)
    assert abs(price_from_sqrt(pool(), sq) - 200.0) < 1e-6


def test_cl_swap_decode_direction():
    import math
    p = pool()
    sq = int(math.sqrt(0.5) * swaps.Q96)
    # token-to-USDC: pool receives token1 (+), pays USDC token0 (-)
    row = {"data": "0x" + w(-1_000_000_000) + w(5 * 10 ** 8) + w(sq) + w(10 ** 12) + w(-6931),
           "topics": [swaps.TOPIC_CL_SWAP, "0x" + "00" * 12 + "11" * 20, "0x" + "00" * 12 + "22" * 20],
           "ts_ms": 1, "block": 1, "log_index": 0, "tx": "0xt", "address": "0xpool"}
    t = swaps.decode_cl(p, row)
    assert t.quote_out and t.quote_abs == 1000.0 and t.token_abs == 5.0 and abs(t.price - 200) < 1e-6


def test_twap_piecewise_constant():
    def tick(ts, price):
        return Tick(ts, ts, 0, price, 1.0, 1.0, True, "0x", "", "")
    path = Path([tick(0, 100.0), tick(50, 110.0), tick(75, 90.0)])
    # [0,100]: 100 for 50, 110 for 25, 90 for 25 -> 100
    assert abs(path.twap(0, 100) - 100.0) < 1e-9
    assert abs(path.twap(60, 80) - (110 * 15 + 90 * 5) / 20) < 1e-9
    assert path.twap(-10, -5) is None


def test_cp_swap_uses_same_tx_sync():
    p = pool("cp", token_is_token0=False)  # token0 = USDC
    sync = {"data": "0x" + w(200_000 * 10 ** 6) + w(1000 * 10 ** 8), "topics": [swaps.TOPIC_CP_SYNC],
            "ts_ms": 5, "block": 5, "log_index": 0, "tx": "0xa", "address": "0xpool"}
    swap = {"data": "0x" + w(0) + w(10 ** 8) + w(199 * 10 ** 6) + w(0),
            "topics": [swaps.TOPIC_CP_SWAP, "0x" + "00" * 32, "0x" + "00" * 32],
            "ts_ms": 5, "block": 5, "log_index": 1, "tx": "0xa", "address": "0xpool"}
    ticks = swaps.ticks_for(p, [sync, swap])
    assert len(ticks) == 1 and abs(ticks[0].price - 200.0) < 1e-9 and ticks[0].quote_out
