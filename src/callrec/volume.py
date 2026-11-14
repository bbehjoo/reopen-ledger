"""Volume shares by heuristic (METHODS.md section 9b). Supporting numbers, never a headline; no address is
named, only shares of USD volume carrying each boolean.

The address of a swap is its `recipient` (concentrated pools), a proxy: routers and aggregators can be the
recipient for many users. An address that is the recipient of more than ROUTER_LIKE swaps in a token's
pools on one UTC day is treated as router-like and left out of OV1.

  OV1_round_trip_10m  the same address takes both directions (token-to-USDC and USDC-to-token) in the
                      token's pools within 10 minutes; both legs carry the flag
  OV3_sandwich_leg    in one block and one pool, an address's swap is followed by another address's swap in
                      the same direction and then by the first address's swap in the other direction; the
                      first address's two legs carry the flag
  OV2_shared_funding  not measured (needs the funding graph of every address); reported as null
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

ROUTER_LIKE = 200
ROUND_TRIP_MS = 600_000


DAY_MS = 86_400_000


def shares_from_paths(pool_paths, lo_ms: int, hi_ms: int) -> dict:
    """Over [lo, hi], one UTC day at a time (a round trip across midnight UTC is not joined): the same
    shares as `shares`, from array-backed swaps.Path objects (tape.PoolPath list of one token)."""
    tot = {"volume_usd": 0.0, "swaps": 0, "v1": 0.0, "v3": 0.0, "either": 0.0}
    day = (lo_ms // DAY_MS) * DAY_MS
    while day <= hi_ms:
        a, b = max(lo_ms, day), min(hi_ms, day + DAY_MS - 1)
        legs = []
        for pp in pool_paths:
            path = pp.path
            i, j = path.index_range(a, b)
            for k in range(i, j):
                f = pp.usd(path._ts[k])
                if not f:
                    continue
                legs.append((path._ts[k], path.block[k], path.li[k], pp.pool_id,
                             path.recips[path.rid[k]] if path.recips else "", bool(path.qout[k]), path.qabs[k] * f))
        if legs:
            r = _flag(legs)
            for key in ("volume_usd", "swaps", "v1", "v3", "either"):
                tot[key] += r[key]
        day += DAY_MS
    t = tot["volume_usd"]
    return {"volume_usd": t, "swaps": tot["swaps"],
            "OV1_round_trip_10m_share": tot["v1"] / t if t else None,
            "OV3_sandwich_leg_share": tot["v3"] / t if t else None,
            "OV2_shared_funding_share": None,
            "either_share": tot["either"] / t if t else None}


def shares(ticks_by_pool: dict[str, list], usd_of) -> dict:
    """ticks_by_pool: pool id -> [swaps.Tick]; usd_of(pool_id, ts_ms) -> USD per quote unit."""
    legs = []   # (ts, block, log_index, pool, addr, quote_out, usd)
    for pid, ticks in ticks_by_pool.items():
        for t in ticks:
            f = usd_of(pid, t.ts_ms)
            if not f:
                continue
            legs.append((t.ts_ms, t.block, t.log_index, pid, t.recipient.lower(), t.quote_out, t.quote_abs * f))
    r = _flag(legs)
    total = r["volume_usd"]
    return {"volume_usd": total, "swaps": r["swaps"],
            "OV1_round_trip_10m_share": (r["v1"] / total) if total else None,
            "OV3_sandwich_leg_share": (r["v3"] / total) if total else None,
            "OV2_shared_funding_share": None,
            "either_share": (r["either"] / total) if total else None}


def _flag(legs: list[tuple]) -> dict:
    legs.sort()
    total = sum(x[6] for x in legs)
    per_day = defaultdict(lambda: defaultdict(int))
    for x in legs:
        per_day[datetime.fromtimestamp(x[0] / 1000, UTC).date()][x[4]] += 1
    flagged_ov1, flagged_ov3 = set(), set()
    by_addr = defaultdict(list)
    for i, x in enumerate(legs):
        d = datetime.fromtimestamp(x[0] / 1000, UTC).date()
        if per_day[d][x[4]] <= ROUTER_LIKE:
            by_addr[x[4]].append(i)
    for idxs in by_addr.values():
        j = 0
        for k in range(len(idxs)):
            while legs[idxs[k]][0] - legs[idxs[j]][0] > ROUND_TRIP_MS:
                j += 1
            for m in range(j, k):
                if legs[idxs[m]][5] != legs[idxs[k]][5]:
                    flagged_ov1.update((idxs[m], idxs[k]))
    by_block_pool = defaultdict(list)
    for i, x in enumerate(legs):
        by_block_pool[(x[1], x[3])].append(i)
    for idxs in by_block_pool.values():
        if len(idxs) < 3:
            continue
        idxs.sort(key=lambda i: legs[i][2])
        for a in range(len(idxs)):
            for c in range(a + 2, len(idxs)):
                ia, ic = idxs[a], idxs[c]
                if legs[ia][4] != legs[ic][4] or legs[ia][5] == legs[ic][5]:
                    continue
                mids = idxs[a + 1: c]
                if any(legs[ib][4] != legs[ia][4] and legs[ib][5] == legs[ia][5] for ib in mids):
                    flagged_ov3.update((ia, ic))
    v1 = sum(legs[i][6] for i in sorted(flagged_ov1))
    v3 = sum(legs[i][6] for i in sorted(flagged_ov3))
    either = sum(legs[i][6] for i in sorted(flagged_ov1 | flagged_ov3))
    return {"volume_usd": total, "swaps": len(legs), "v1": v1, "v3": v3, "either": either}
