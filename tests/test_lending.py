import pytest

from callrec import lending
from callrec.lending import AaveReserve, AaveSpoke, AaveUser, MorphoMarket, MorphoPosition

TOK = "0xb20000000000000000000078ee7ce2fe4908108c"
TOK2 = "0xb2000000000000000000001e800a7f5189430cd0"


def test_morpho_lif_matches_research_values():
    assert lending.morpho_lif(0.625) == pytest.approx(1.126761, abs=1e-6)
    assert lending.morpho_lif(0.77) == pytest.approx(1.074114, abs=1e-6)


def test_morpho_shock_liquidation_and_underwater():
    # one position: 100 tokens (8 dec) at $200 -> $20,000 collateral; debt $12,000; LLTV 0.625
    price = int(200 * 10 ** 6 / 10 ** 8 * 1e36)        # USDC raw per token raw, scaled 1e36
    m = MorphoMarket("0xid", TOK, 0.625, price, 12_000 * 10 ** 6, 12_000 * 10 ** 6 * 10 ** 6)
    m.positions = [MorphoPosition("0xu", 100 * 10 ** 8, 12_000 * 10 ** 6 * 10 ** 6)]
    assert m.debt_raw(m.positions[0]) == pytest.approx(12_000 * 10 ** 6, rel=1e-9)
    # healthy at 5%: 19,000 * 0.625 = 11,875 < 12,000 -> already liquidatable at 5%
    r5 = lending.morpho_shock(m, 0.05)
    assert r5["positions_liquidatable"] == 1
    assert r5["liquidation_flow_usd"] == pytest.approx(min(19_000, 12_000 * lending.morpho_lif(0.625)), rel=1e-6)
    assert r5["underwater_debt_usd"] == 0
    r50 = lending.morpho_shock(m, 0.5)  # collateral 10,000 < debt 12,000
    assert r50["underwater_debt_usd"] == pytest.approx(12_000, rel=1e-9)


def test_aave_bonus_curve_matches_deployed_check():
    sp = AaveSpoke({}, [])
    # LENDING.md 2.6: calculateLiquidationBonus(0.9e18, 9000, hf, 10550) -> 10500 @0.99, 10522 @0.95, 10550 @0.90
    assert lending.aave_bonus(sp, 1.055, 0.99) == pytest.approx(1.0500, abs=1e-4)
    assert lending.aave_bonus(sp, 1.055, 0.95) == pytest.approx(1.0522, abs=1e-4)
    assert lending.aave_bonus(sp, 1.055, 0.90) == pytest.approx(1.055, abs=1e-9)


def test_aave_shock_restores_target_and_respects_other_collateral():
    res = {0: AaveReserve(0, TOK, 8, 200.0, {0: 0.70}, {0: 1.055}),
           1: AaveReserve(1, TOK2, 8, 100.0, {0: 0.65}, {0: 1.055})}
    # user A: only TOK, $20k collateral, $13.5k debt -> HF 1.037; at 10% shock HF 0.933
    a = AaveUser("0xa", {0: 100.0}, {0: 0}, 13_500.0)
    # user B: TOK and TOK2, healthy enough that a 10% shock on TOK alone does not liquidate
    b = AaveUser("0xb", {0: 50.0, 1: 100.0}, {0: 0, 1: 0}, 8_000.0)
    sp = AaveSpoke(res, [a, b])
    r = lending.aave_shock(sp, TOK, 0.10)
    assert r["positions_liquidatable"] == 1
    hf = 18_000 * 0.70 / 13_500
    lb = lending.aave_bonus(sp, 1.055, hf)
    repay = 13_500 * (1.24 - hf) / (1.24 - lb * 0.70)
    assert r["liquidation_flow_usd"] == pytest.approx(repay * lb, rel=1e-9)
    assert r["underwater_debt_usd"] == 0


def test_address_constants_are_20_bytes():
    import re

    from callrec import lending as L
    assert re.fullmatch(r"0x[0-9a-f]{40}", L.MORPHO)
    assert L.MORPHO == "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb".lower()


def test_lending_totals_count_each_position_once():
    from callrec import coverage
    snap = {"morpho": {"markets": []}, "aave_v4": {
        "reserves": [{"id": 0, "token": TOK, "decimals": 8, "price_usd": 100.0, "cf": {"0": 0.7}, "max_lb": {"0": 1.05}},
                     {"id": 1, "token": TOK2, "decimals": 8, "price_usd": 50.0, "cf": {"0": 0.6}, "max_lb": {"0": 1.05}}],
        "users": [{"user": "0xa", "supplied": {"0": 1.0, "1": 2.0}, "keys": {}, "debt_usd": 80.0}]}}
    t = coverage._lending_totals(snap)
    assert t["aave_v4"] == {"collateral_usd": 200.0, "debt_usd": 80.0, "borrowers": 1}
    assert t["total"]["debt_usd"] == 80.0
