"""Lending positions against stock collateral, and the liquidation flow at a shocked oracle price
(METHODS.md section 8). Formulas from docs/research/LENDING.md (Morpho Blue at bc479b9, Aave V4 at 2524fe4).

Snapshot: positions read at one block with eth_call (Morpho `position`/`market`/`price`; Aave V4 spoke
views and AaveOracle prices), written to data/raw/snapshots/lending/<block>.json, which is the replay input.
Borrowers are enumerated from events (streams `morpho` and `aave_v4`).

Shock s on token k moves the price that the market's oracle reads for k to p_k * (1 - s); every other price
is unchanged (a per-token shock). Per market and token:
  liquidation_flow_usd  value, at the shocked price, of the collateral of k a liquidator would seize
  underwater_debt_usd   debt of positions whose collateral (all of it, at shocked prices) is below the debt
Aave V4 positions with several collateral reserves: the shocked reserve is liquidated first (the convention
in LENDING.md 2.6); the repaid amount restores the target health factor or hits a dust rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config
from .abi import enc_address, enc_uint, selector, words

WAD = 10 ** 18
MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
LIQ_CURSOR = 0.3
MAX_LIF = 1.15
SHOCKS = (0.05, 0.10, 0.20)


def morpho_lif(lltv: float) -> float:
    return min(MAX_LIF, 1 / (1 - LIQ_CURSOR * (1 - lltv)))


# --- Morpho Blue -------------------------------------------------------------------------------------------
@dataclass
class MorphoPosition:
    user: str
    collateral_raw: int
    borrow_shares: int


@dataclass
class MorphoMarket:
    id: str
    token: str
    lltv: float
    price_1e36: int                 # oracle.price(): quote raw units per collateral raw unit, scaled 1e36
    total_borrow_assets: int
    total_borrow_shares: int
    loan_decimals: int = 6
    positions: list[MorphoPosition] = field(default_factory=list)

    def debt_raw(self, p: MorphoPosition) -> int:
        # toAssetsUp: ceil(shares * (totalAssets + 1) / (totalShares + 1e6))
        num = p.borrow_shares * (self.total_borrow_assets + 1)
        den = self.total_borrow_shares + 10 ** 6
        return -(-num // den)


def morpho_shock(m: MorphoMarket, s: float) -> dict:
    price = m.price_1e36 * (1 - s)
    lif = morpho_lif(m.lltv)
    flow = under = 0.0
    n_liq = 0
    for p in m.positions:
        d = m.debt_raw(p)
        if d == 0:
            continue
        coll_val = p.collateral_raw * price / 1e36          # loan raw units
        if coll_val * m.lltv < d:
            n_liq += 1
            seized = min(p.collateral_raw, d * lif * 1e36 / price)
            flow += seized * price / 1e36
        if coll_val < d:
            under += d
    scale = 10 ** m.loan_decimals
    return {"liquidation_flow_usd": flow / scale, "underwater_debt_usd": under / scale, "positions_liquidatable": n_liq}


# --- Aave V4 -----------------------------------------------------------------------------------------------
@dataclass
class AaveReserve:
    id: int
    token: str
    decimals: int
    price: float                     # USD (AaveOracle, 8 decimals already applied)
    cf: dict[int, float]             # dynamic config key -> collateral factor
    max_lb: dict[int, float]         # key -> max liquidation bonus (1.055 = 5.5%)


@dataclass
class AaveUser:
    user: str
    supplied: dict[int, float]       # reserve id -> token amount (decimal), only reserves used as collateral
    keys: dict[int, int]             # reserve id -> dynamic config key
    debt_usd: float


@dataclass
class AaveSpoke:
    reserves: dict[int, AaveReserve]
    users: list[AaveUser]
    target_hf: float = 1.24
    hf_for_max_bonus: float = 0.90
    bonus_factor: float = 0.90
    dust_usd: float = 1000.0


def aave_bonus(sp: AaveSpoke, max_lb: float, hf: float) -> float:
    if hf <= sp.hf_for_max_bonus:
        return max_lb
    min_lb = 1 + sp.bonus_factor * (max_lb - 1)
    return min_lb + (max_lb - min_lb) * (1 - hf) / (1 - sp.hf_for_max_bonus)


def aave_shock(sp: AaveSpoke, token: str, s: float) -> dict:
    k = next((rid for rid, r in sp.reserves.items() if r.token == token), None)
    if k is None:
        return {"liquidation_flow_usd": 0.0, "underwater_debt_usd": 0.0, "positions_liquidatable": 0}
    flow = under = 0.0
    n_liq = 0
    for u in sp.users:
        if u.debt_usd <= 0 or k not in u.supplied:
            continue
        prices = {rid: sp.reserves[rid].price * ((1 - s) if rid == k else 1.0) for rid in u.supplied}
        coll = {rid: u.supplied[rid] * prices[rid] for rid in u.supplied}
        weighted = sum(coll[rid] * sp.reserves[rid].cf.get(u.keys.get(rid, 0), 0.0) for rid in u.supplied)
        hf = weighted / u.debt_usd
        if sum(coll.values()) < u.debt_usd:
            under += u.debt_usd
        if hf >= 1:
            continue
        n_liq += 1
        cf_k = sp.reserves[k].cf.get(u.keys.get(k, 0), 0.0)
        lb = aave_bonus(sp, sp.reserves[k].max_lb.get(u.keys.get(k, 0), 1.0), hf)
        denom = sp.target_hf - lb * cf_k
        r_target = u.debt_usd * (sp.target_hf - hf) / denom if denom > 0 else u.debt_usd
        repay = min(u.debt_usd, r_target)
        if u.debt_usd - repay < sp.dust_usd:
            repay = u.debt_usd
        seized_val = repay * lb
        if seized_val > coll[k] or coll[k] - seized_val < sp.dust_usd:
            seized_val = coll[k]
        flow += seized_val
    return {"liquidation_flow_usd": flow, "underwater_debt_usd": under, "positions_liquidatable": n_liq}


# --- snapshot I/O ------------------------------------------------------------------------------------------
def snapshot_dir():
    return config.data_dir() / "raw" / "snapshots" / "lending"


def save_snapshot(doc: dict) -> str:
    d = snapshot_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{doc['block']}.json"
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return str(p)


def latest_snapshot(at_or_before_block: int | None = None) -> dict | None:
    d = snapshot_dir()
    if not d.exists():
        return None
    blocks = sorted(int(p.stem) for p in d.glob("*.json"))
    if at_or_before_block is not None:
        blocks = [b for b in blocks if b <= at_or_before_block]
    if not blocks:
        return None
    return json.loads((d / f"{blocks[-1]}.json").read_text(encoding="utf-8"))


def spoke_from_snapshot(doc: dict) -> AaveSpoke | None:
    a = doc.get("aave_v4")
    if not a:
        return None
    res = {int(r["id"]): AaveReserve(int(r["id"]), r["token"].lower(), int(r["decimals"]), float(r["price_usd"]),
                                     {int(k): float(v) for k, v in r["cf"].items()},
                                     {int(k): float(v) for k, v in r["max_lb"].items()}) for r in a["reserves"]}
    users = [AaveUser(u["user"], {int(k): float(v) for k, v in u["supplied"].items()},
                      {int(k): int(v) for k, v in u.get("keys", {}).items()}, float(u["debt_usd"])) for u in a["users"]]
    lc = a.get("liquidation_config", {})
    return AaveSpoke(res, users, lc.get("target_hf", 1.24), lc.get("hf_for_max_bonus", 0.90),
                     lc.get("bonus_factor", 0.90), lc.get("dust_usd", 1000.0))


def morpho_from_snapshot(doc: dict) -> list[MorphoMarket]:
    out = []
    for m in doc.get("morpho", {}).get("markets", []):
        mm = MorphoMarket(m["id"], m["token"].lower(), float(m["lltv"]), int(m["price_1e36"]),
                          int(m["total_borrow_assets"]), int(m["total_borrow_shares"]), int(m.get("loan_decimals", 6)))
        mm.positions = [MorphoPosition(p["user"], int(p["collateral_raw"]), int(p["borrow_shares"])) for p in m["positions"]]
        out.append(mm)
    return out


def shock_table(doc: dict, tokens: list[str]) -> dict[str, dict]:
    """token -> {"liquidation_flow_usd": {"5","10","20"}, "underwater_debt_usd": {...}, "by_market": [...]}"""
    spoke = spoke_from_snapshot(doc)
    markets = morpho_from_snapshot(doc)
    out = {}
    for t in tokens:
        lf, uw, nl, by = {}, {}, {}, []
        for s in SHOCKS:
            key = str(int(round(s * 100)))
            tot_f = tot_u = 0.0
            n = 0
            if spoke:
                a = aave_shock(spoke, t, s)
                tot_f += a["liquidation_flow_usd"]
                tot_u += a["underwater_debt_usd"]
                n += a["positions_liquidatable"]
            for m in markets:
                if m.token == t:
                    b = morpho_shock(m, s)
                    tot_f += b["liquidation_flow_usd"]
                    tot_u += b["underwater_debt_usd"]
                    n += b["positions_liquidatable"]
            lf[key], uw[key], nl[key] = tot_f, tot_u, n
        out[t] = {"liquidation_flow_usd": lf, "underwater_debt_usd": uw, "positions_liquidatable": nl}
    return out


# --- on-chain reads (used by `callrec snapshot lending`) -------------------------------------------------
def _call(rpc, to: str, sig: str, *args: str, block: int | str = "latest") -> list[int]:
    return words(rpc.eth_call(to, selector(sig) + "".join(args), block))


def read_morpho_market(rpc, mid: str, users: list[str], block: int) -> dict:
    mid_hex = mid.lower().removeprefix("0x").rjust(64, "0")
    params = _call(rpc, MORPHO, "idToMarketParams(bytes32)", mid_hex, block=block)
    loan, coll, oracle, _irm, lltv = ("0x" + f"{params[0]:064x}"[-40:], "0x" + f"{params[1]:064x}"[-40:],
                                      "0x" + f"{params[2]:064x}"[-40:], params[3], params[4])
    mk = _call(rpc, MORPHO, "market(bytes32)", mid_hex, block=block)
    try:
        price = _call(rpc, oracle, "price()", block=block)[0]
    except Exception:
        price = None
    from .multicall import aggregate
    res = aggregate(rpc, [(MORPHO, selector("position(bytes32,address)") + mid_hex + enc_address(u)) for u in users],
                    block) if users else []
    pos = []
    for u, r in zip(users, res, strict=True):
        if r is None:
            continue
        w = words(r)
        if w[1] or w[2]:
            pos.append({"user": u, "borrow_shares": str(w[1]), "collateral_raw": str(w[2])})
    return {"id": mid.lower(), "token": coll, "loan_token": loan, "oracle": oracle, "lltv": lltv / WAD,
            "price_1e36": str(price) if price is not None else "0", "oracle_reverts": price is None,
            "total_borrow_assets": str(mk[2]), "total_borrow_shares": str(mk[3]), "loan_decimals": 6,
            "positions": sorted(pos, key=lambda p: p["user"])}


def read_aave_spoke(rpc, spoke: str, oracle: str, stock_tokens: set[str], users: list[str], block: int,
                    debt_reserve: int = 7) -> dict:
    n = _call(rpc, spoke, "getReserveCount()", block=block)[0]
    reserves = []
    for rid in range(n):
        r = _call(rpc, spoke, "getReserve(uint256)", enc_uint(rid), block=block)
        token = "0x" + f"{r[0]:064x}"[-40:]
        dec = r[3]
        key = r[6]
        price = _call(rpc, oracle, "getReservePrice(uint256)", enc_uint(rid), block=block)[0] / 1e8
        cf, mlb = {}, {}
        for kk in range(key + 1):
            c = _call(rpc, spoke, "getDynamicReserveConfig(uint256,uint32)", enc_uint(rid), enc_uint(kk), block=block)
            cf[str(kk)] = c[0] / 10_000
            mlb[str(kk)] = c[1] / 10_000
        reserves.append({"id": rid, "token": token, "decimals": dec, "price_usd": price, "cf": cf, "max_lb": mlb,
                         "stock": token in stock_tokens})
    lc = _call(rpc, spoke, "getLiquidationConfig()", block=block)
    stock_ids = [r["id"] for r in reserves if r["stock"]]
    dec_of = {r["id"]: r["decimals"] for r in reserves}
    debt_price = next(r["price_usd"] for r in reserves if r["id"] == debt_reserve)
    debt_dec = dec_of[debt_reserve]
    from .multicall import aggregate
    per_user = 3 * len(stock_ids) + 1
    calls = []
    for u in users:
        for rid in stock_ids:
            calls.append((spoke, selector("getUserSuppliedAssets(uint256,address)") + enc_uint(rid) + enc_address(u)))
            calls.append((spoke, selector("getUserReserveStatus(uint256,address)") + enc_uint(rid) + enc_address(u)))
            calls.append((spoke, selector("getUserPosition(uint256,address)") + enc_uint(rid) + enc_address(u)))
        calls.append((spoke, selector("getUserTotalDebt(uint256,address)") + enc_uint(debt_reserve) + enc_address(u)))
    allres = aggregate(rpc, calls, block, chunk=250)
    out_users = []
    for ui, u in enumerate(users):
        res = allres[ui * per_user: (ui + 1) * per_user]
        supplied, keys = {}, {}
        for i, rid in enumerate(stock_ids):
            a, st, ps = res[3 * i], res[3 * i + 1], res[3 * i + 2]
            if a is None or st is None:
                continue
            amt = words(a)[0] / 10 ** dec_of[rid]
            using = words(st)[0] == 1
            if amt > 0 and using:
                supplied[str(rid)] = amt
                if ps:
                    keys[str(rid)] = words(ps)[4]
        d = res[-1]
        debt = 0.0 if d is None else words(d)[0] / 10 ** debt_dec * debt_price
        if supplied or debt:
            out_users.append({"user": u, "supplied": supplied, "keys": keys, "debt_usd": debt})
    return {"spoke": spoke, "oracle": oracle, "reserves": reserves,
            "liquidation_config": {"target_hf": lc[0] / WAD, "hf_for_max_bonus": lc[1] / WAD,
                                   "bonus_factor": lc[2] / 10_000, "dust_usd": 1000.0},
            "users": sorted(out_users, key=lambda x: x["user"])}
