"""What these markets can absorb (METHODS.md section 8): one snapshot of pool depth and lending positions at
one block, the per-token table built from it, and the schema-2 coverage call.

Inputs (all replayable): data/raw/snapshots/depth/<block>.json, data/raw/snapshots/lending/<block>.json,
the `morpho` and `aave_v4` event streams (who has a position), config/pools.yaml, config/lending.yaml.
"""

from __future__ import annotations

import time
from collections import defaultdict

import yaml

from . import commits, config, depthread, lending, store
from .abi import topic
from .depth import ladder, swap_token_for_quote

MORPHO_EVENTS = {
    "SupplyCollateral": (topic("SupplyCollateral(bytes32,address,address,uint256)"), 3),
    "WithdrawCollateral": (topic("WithdrawCollateral(bytes32,address,address,address,uint256)"), 2),
    "Borrow": (topic("Borrow(bytes32,address,address,address,uint256,uint256)"), 2),
    "Repay": (topic("Repay(bytes32,address,address,uint256,uint256)"), 3),
    "Liquidate": (topic("Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"), 3),
}
AAVE_EVENTS = {   # owner in topic3 for all of these (LENDING.md 2.4)
    "Supply": "0xd986db228cb1fe8392c5f45ff5f2c639b7db6cbd9ca7d1fe70b2de90c2c8c961",
    "Withdraw": "0xfe7813e2866053d5c3938554e517b554fce6666a6561bed9eaa7419b29fa9b68",
    "Borrow": "0xef18174796a5d2f91d51dc5e907a4d7867bbd6e800f6225168e0453d581d0dcd",
    "Repay": "0xd765a0263e8a360da8dd4fdb8c0dc5553adec12a96f29a462cdb45e5bea407dd",
    "SetUsingAsCollateral": "0x4763df430bc5274807f8ab4ce0734e7898513638418d6eec0c5285ef85f7f51f",
    "LiquidationCall": "0x2a1f12d996f530f89d8038aa293f9fde81cac44b6dfd6225e3358d09b78a4a37",
}
IMPACT_SIZES = (10_000.0, 100_000.0)


def lending_cfg() -> dict:
    return yaml.safe_load((config.config_dir() / "lending.yaml").read_text(encoding="utf-8"))


def morpho_markets() -> list[dict]:
    return [m for m in lending_cfg()["markets"] if m["protocol"] == "morpho_blue"]


def aave_cfg() -> dict:
    return lending_cfg()["protocols"]["aave_v4"]


def stream_specs() -> list[dict]:
    ms = morpho_markets()
    a = aave_cfg()
    return [
        {"stream": "morpho", "addresses": [lending.MORPHO],
         "topics": [sorted(t for t, _ in MORPHO_EVENTS.values()), sorted(m["id"].lower() for m in ms)],
         # publicnode serves logs from about block 51.0M; two dust markets created before it (METAc 0xa8835b56,
         # $0 borrowed; NVDAc 0xfef5641f, $0.15 borrowed) may miss positions opened before then
         "start": max(51_000_000, min(int(m["creation_block"]) for m in ms if m.get("creation_block")))},
        {"stream": "aave_v4", "addresses": [a["spoke"].lower()], "topics": [sorted(AAVE_EVENTS.values())],
         "start": 51_478_830},
    ]


def morpho_users(to_ms: int | None = None) -> dict[str, list[str]]:
    pos = {t: i for t, i in MORPHO_EVENTS.values()}
    out = defaultdict(set)
    for row in store.read("morpho", to_ms=to_ms):
        i = pos.get(row["topics"][0])
        if i is not None and len(row["topics"]) > i:
            out[row["topics"][1]].add("0x" + row["topics"][i][-40:])
    return {k: sorted(v) for k, v in out.items()}


def aave_users(to_ms: int | None = None) -> list[str]:
    s = set()
    for row in store.read("aave_v4", to_ms=to_ms):
        if row["topics"] and row["topics"][0] in AAVE_EVENTS.values() and len(row["topics"]) > 3:
            s.add("0x" + row["topics"][3][-40:])
    return sorted(s)


def snapshot_all(rpc, block: int | None = None) -> dict:
    """Read depth and lending at one block and save both snapshots. Returns a summary."""
    from . import pools as poolsmod
    from .chain import schedule
    if block is None:
        block = rpc.block_number() - 30
    ts = schedule().ts_ms(block)
    summary = {"block": block, "ts_ms": ts}
    # depth
    plist = poolsmod.load_pools()
    sv = ((poolsmod.raw_config().get("contracts") or {}).get("uniswap_v4_state_view") or {}).get("address")
    sv = sv.lower() if sv else None
    pools_raw, errors = {}, {}
    for p in plist:
        try:
            if p.kind == "cl":
                _, raw = depthread.read_cl(rpc, p, block)
            elif p.kind == "v4" and sv:
                _, raw = depthread.read_v4(rpc, p, sv, block)
            elif p.kind == "cp":
                _, raw = depthread.read_cp(rpc, p, block)
            else:
                continue
            pools_raw[p.id] = raw
        except Exception as e:
            errors[p.id] = f"{type(e).__name__}: {e}"[:200]
    depthread.save({"block": block, "ts_ms": ts, "pools": pools_raw, "errors": errors})
    summary["depth_pools"] = len(pools_raw)
    summary["depth_errors"] = len(errors)
    # lending
    doc = {"block": block, "ts_ms": ts, "morpho": {"markets": []}, "aave_v4": None, "errors": {}}
    users = morpho_users()
    for m in morpho_markets():
        try:
            doc["morpho"]["markets"].append(lending.read_morpho_market(rpc, m["id"], users.get(m["id"].lower(), []), block))
        except Exception as e:
            doc["errors"][m["id"]] = f"{type(e).__name__}: {e}"[:200]
    try:
        from . import registry
        stock = {t["address"] for t in registry.load()["tokens"]}
        a = aave_cfg()
        doc["aave_v4"] = lending.read_aave_spoke(rpc, a["spoke"].lower(), a["spoke_oracle"].lower(), stock,
                                                 aave_users(), block)
    except Exception as e:
        doc["errors"]["aave_v4"] = f"{type(e).__name__}: {e}"[:200]
    lending.save_snapshot(doc)
    summary["morpho_markets"] = len(doc["morpho"]["markets"])
    summary["aave_users"] = len((doc["aave_v4"] or {}).get("users", []))
    summary["lending_errors"] = doc["errors"]
    return summary


def absorb_table(inp, at_ms: int) -> dict | None:
    """Per slate token at the latest pair of snapshots at or before at_ms."""
    from . import pools as poolsmod
    from .calendar import et
    deps = depthread.snapshots(at_ms)
    if not deps:
        return None
    dsnap = deps[-1]
    lsnap = lending.latest_snapshot(dsnap["block"])
    plist = {p.id: p for p in poolsmod.load_pools()}
    by_token = defaultdict(list)
    for pid, raw in dsnap["pools"].items():
        p = plist.get(pid)
        if p is None:
            continue
        usd = poolsmod.usd_factor(p.quote, at_ms)(dsnap["ts_ms"])
        if not usd:
            continue
        by_token[p.token].append((p, depthread.state_from_raw(p, raw), usd))
    shocks = lending.shock_table(lsnap, sorted(inp.feed_of)) if lsnap else {}
    rows = []
    for token in sorted(inp.feed_of):
        ref = inp.ref(token)
        u = ref.at(dsnap["ts_ms"]) if ref else None
        refp = ref.price(u) if u else None
        states = by_token.get(token, [])
        lad = ladder([(st, usd) for _, st, usd in states], refp) if (states and refp) else None
        impact = {}
        if states:
            # primary pool for impact: the one with the most downward depth in the first 2%
            from .depth import quote_out
            p0, st0, usd0 = max(states, key=lambda x: quote_out(x[1], x[1].token_price(), x[1].token_price() * 0.98) * x[2])
            for n in IMPACT_SIZES:
                imp = swap_token_for_quote(st0, n / usd0, fee=(p0.fee or 0))
                # None: the pool's liquidity in the band read (down to 70% of the price) cannot fill it
                impact[n] = imp.get("impact_bps") if imp.get("filled") else None
        sh = shocks.get(token, {})
        stale = bool(u and (dsnap["ts_ms"] - u.ts_ms) > 26 * 3_600_000 and not _in_closed(dsnap["ts_ms"]))
        flags = []
        if stale:
            flags.append("S1_stale_reference")
        if states and refp:
            pp = st0.token_price() * usd0   # the deepest pool's price in USD
            if abs(pp / refp - 1) > 0.02 and not _in_closed(dsnap["ts_ms"]):
                flags.append("S2_dex_gap_large")
        if lad and lad["move_2pct_usd"] < 10_000:
            flags.append("D1_depth_thin")
        tier = "stale" if stale else ("insufficient_data" if not lad else
                                      ("no_flags" if not flags else ("one_flag" if len(flags) == 1 else "flagged")))
        absorb = {k: v for k, v in (lad or {}).get("absorb_5pct_below_usd", {}).items()}
        lf = sh.get("liquidation_flow_usd", {})
        cov = {k: (absorb[k] / lf[k] if lf.get(k) else None) for k in absorb}
        rows.append({"token": token, "ref_price": refp, "pools": len(states),
                     "move_1pct_usd": (lad or {}).get("move_1pct_usd"), "move_2pct_usd": (lad or {}).get("move_2pct_usd"),
                     "impact_10k_bps": impact.get(10_000.0), "impact_100k_bps": impact.get(100_000.0),
                     "absorb_5pct_below_usd": absorb, "liquidation_flow_usd": lf,
                     "underwater_debt_usd": sh.get("underwater_debt_usd", {}),
                     "positions_liquidatable": sh.get("positions_liquidatable", {}), "coverage": cov,
                     "headroom_usd": {k: absorb[k] - lf.get(k, 0.0) for k in absorb},
                     "flags": flags, "tier": tier})
    markets = _markets_summary(lsnap) if lsnap else []
    note = ("Lending positions read: Morpho Blue and Aave V4 (Equities Hub). Euler v2 lists one stock "
            "collateral vault holding nothing at the snapshot.") if lsnap else "No lending snapshot."
    if lsnap and lsnap.get("errors"):
        note += " Not read in this snapshot: " + ", ".join(sorted(lsnap["errors"])) + "."
    return {"block": dsnap["block"], "ts_ms": dsnap["ts_ms"], "at_et": et(dsnap["ts_ms"]),
            "lending_block": lsnap["block"] if lsnap else None, "tokens": rows, "markets": markets,
            "lending_totals": _lending_totals(lsnap) if lsnap else None,
            "coverage_note": note, "depth_errors": dsnap.get("errors", {})}


def _in_closed(ts_ms: int) -> bool:
    from datetime import UTC, datetime, timedelta

    from .calendar import windows_between
    d = datetime.fromtimestamp(ts_ms / 1000, UTC).date()
    return any(w.kind == 1 and w.start_ms <= ts_ms <= w.reopen_ms
               for w in windows_between(d - timedelta(days=5), d + timedelta(days=2)))


def _lending_totals(lsnap: dict) -> dict:
    """Per protocol: collateral enabled (USD at the oracle), debt and borrowers, each position counted once."""
    out = {}
    ms = lending.morpho_from_snapshot(lsnap)
    out["morpho_blue"] = {
        "collateral_usd": sum(sum(p.collateral_raw for p in m.positions) * m.price_1e36 / 1e36 / 1e6 for m in ms),
        "debt_usd": sum(sum(m.debt_raw(p) for p in m.positions) / 1e6 for m in ms),
        "borrowers": sum(1 for m in ms for p in m.positions if p.borrow_shares > 0)}
    sp = lending.spoke_from_snapshot(lsnap)
    if sp:
        out["aave_v4"] = {
            "collateral_usd": sum(u.supplied[rid] * sp.reserves[rid].price for u in sp.users for rid in u.supplied),
            "debt_usd": sum(u.debt_usd for u in sp.users),
            "borrowers": sum(1 for u in sp.users if u.debt_usd > 0)}
    out["total"] = {k: sum(v[k] for v in out.values()) for k in ("collateral_usd", "debt_usd", "borrowers")}
    return out


def _markets_summary(lsnap: dict) -> list[dict]:
    out = []
    for m in lending.morpho_from_snapshot(lsnap):
        coll = sum(p.collateral_raw for p in m.positions) * m.price_1e36 / 1e36 / 1e6
        debt = sum(m.debt_raw(p) for p in m.positions) / 1e6
        out.append({"protocol": "morpho_blue", "market": m.id[:10], "collateral_symbol": None, "token": m.token,
                    "collateral_usd": coll, "debt_usd": debt, "positions": len(m.positions),
                    "oracle_note": "Chainlink 24/5 feed, no staleness check", "status": "read"})
    sp = lending.spoke_from_snapshot(lsnap)
    if sp:
        for rid, r in sorted(sp.reserves.items()):
            if r.cf.get(0, 0) <= 0:
                continue
            coll = sum(u.supplied.get(rid, 0) * r.price for u in sp.users)
            debt = sum(u.debt_usd for u in sp.users if rid in u.supplied)   # a user with several reserves counts in each
            out.append({"protocol": "aave_v4", "market": f"reserve {rid}", "collateral_symbol": None, "token": r.token,
                        "collateral_usd": coll, "debt_usd": debt, "debt_note": "debt of positions using this reserve",
                        "positions": sum(1 for u in sp.users if rid in u.supplied),
                        "oracle_note": "Chainlink 24/5 feed via AaveOracle, no staleness check", "status": "read"})
    return out


def liquidations_between(a_ms: int, b_ms: int) -> dict[str, float]:
    """USD value of collateral seized per token by liquidation events in [a, b] (Morpho `Liquidate`,
    Aave V4 `LiquidationCall`), valued with the latest lending snapshot's prices."""
    snap = lending.latest_snapshot()
    if not snap:
        return {}
    out = defaultdict(float)
    mk = {m["id"].lower(): m for m in snap.get("morpho", {}).get("markets", [])}
    liq_topic = MORPHO_EVENTS["Liquidate"][0]
    from .abi import words
    for row in store.read("morpho", from_ms=a_ms, to_ms=b_ms):
        if row["topics"][0] != liq_topic:
            continue
        m = mk.get(row["topics"][1].lower())
        if not m:
            continue
        seized = words(row["data"])[2]       # repaidAssets, repaidShares, seizedAssets, ...
        out[m["token"]] += seized * int(m["price_1e36"]) / 1e36 / 1e6
    a = snap.get("aave_v4") or {}
    res = {int(r["id"]): r for r in a.get("reserves", [])}
    for row in store.read("aave_v4", from_ms=a_ms, to_ms=b_ms):
        if row["topics"][0] != AAVE_EVENTS["LiquidationCall"]:
            continue
        r = res.get(int(row["topics"][1], 16))
        if not r:
            continue
        w = words(row["data"])
        # data: liquidator, receiveShares, debtAmountRestored, drawnSharesLiquidated, premiumDelta(3 words),
        #       collateralAmountRemoved, ...
        removed = w[7] if len(w) > 7 else 0
        out[r["token"]] += removed / 10 ** int(r["decimals"]) * float(r["price_usd"])
    return dict(out)


def coverage_bytes_for_window(w) -> bytes:
    """Schema 2 for a closed window, from the latest snapshot (taken by `snapshot if-coverage-due`)."""
    from .build import Inputs
    now = int(time.time() * 1000)
    inp = Inputs(now)
    t = absorb_table(inp, now)
    if t is None:
        raise RuntimeError("no depth snapshot")
    if now - t["ts_ms"] > 2 * 3_600_000:
        raise RuntimeError("latest snapshot is older than 2 hours")
    entries = []
    for row in t["tokens"]:
        a, lf, uw = row["absorb_5pct_below_usd"], row["liquidation_flow_usd"], row["underwater_debt_usd"]
        entries.append(commits.CoverageEntry(row["token"], tuple(a.get(k) for k in ("5", "10", "20")),
                                             tuple(lf.get(k) for k in ("5", "10", "20")),
                                             tuple(uw.get(k) for k in ("5", "10", "20"))))
    return commits.encode_coverage(t["block"], entries)
