from callrec.swaps import Tick
from callrec.volume import shares


def t(ts, block, li, addr, quote_out, q=100.0):
    return Tick(ts, block, li, 100.0, q, 1.0, quote_out, f"0x{block}{li}", "0xrouter", addr)


def test_round_trip_and_sandwich_shares():
    ticks = [
        t(0, 1, 0, "0xa", True), t(60_000, 2, 0, "0xa", False),          # round trip within 10 min
        t(10_000_000, 3, 0, "0xb", True), t(20_000_000, 4, 0, "0xb", False),   # too far apart
        t(30_000_000, 5, 0, "0xs", False), t(30_000_000, 5, 1, "0xv", False), t(30_000_000, 5, 2, "0xs", True),
    ]
    r = shares({"p": ticks}, lambda pid, ts: 1.0)
    assert r["swaps"] == 7 and r["volume_usd"] == 700.0
    # OV1: 0xa's two legs; 0xs also round-trips within 10 min (same block): 4 legs = 400
    assert abs(r["OV1_round_trip_10m_share"] - 400 / 700) < 1e-9
    assert abs(r["OV3_sandwich_leg_share"] - 200 / 700) < 1e-9
    assert r["OV2_shared_funding_share"] is None
