"""The weekend tape and the DEX-implied baseline (METHODS.md section 6). Pure functions.

Inputs per token: its pools' price paths (swaps.Path), the USD value of each pool's quote asset over time
(1 for USDC; the ETH/USD feed for WETH), and the token's reference Series.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .calendar import Window

HOUR = 3_600_000
LAST_HOUR = HOUR
THIN_LOOKBACK = 12 * HOUR
THIN_MIN_SWAPS = 5
THIN_MIN_USD = 1_000.0
PRIMARY_LOOKBACK = 30 * 24 * HOUR
SIGMA_PRIOR_BPS = 150.0
SIGMA_MIN_WINDOWS = 4
P_CLIP = (0.05, 0.95)
OUTLIER_BPS = 3000.0   # a last-hour DEX price more than 30% from the reference: a broken or empty pool


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


@dataclass
class PoolPath:
    pool_id: str
    path: object                   # swaps.Path
    usd: object                    # callable ts_ms -> USD per quote unit (or None)


def _prefix(pp: PoolPath) -> list[float]:
    """Cumulative USD volume over the pool's swaps (cached on the PoolPath)."""
    pre = getattr(pp, "_prefix", None)
    if pre is None:
        pre = [0.0]
        acc = 0.0
        path = pp.path
        for i in range(len(path)):
            f = pp.usd(path._ts[i])
            if f:
                acc += path.qabs[i] * f
            pre.append(acc)
        pp._prefix = pre
    return pre


def volume_usd(pp: PoolPath, a: int, b: int) -> float:
    import bisect
    pre = _prefix(pp)
    ts = pp.path._ts
    i = bisect.bisect_left(ts, a)
    j = bisect.bisect_right(ts, b)
    return pre[j] - pre[i]


def primary_pool(pools: list[PoolPath], at_ms: int) -> PoolPath | None:
    """The listed pool with the most USD volume over the 30 days before at_ms (ties: pool id)."""
    best, best_v = None, -1.0
    for pp in sorted(pools, key=lambda p: p.pool_id):
        v = volume_usd(pp, at_ms - PRIMARY_LOOKBACK, at_ms)
        if v > best_v:
            best, best_v = pp, v
    return best if best_v > 0 else None


def usd_twap(pp: PoolPath, a: int, b: int) -> float | None:
    tw = pp.path.twap(a, b)
    if tw is None:
        return None
    f = pp.usd((a + b) // 2)
    return tw * f if f else None


@dataclass
class TapeRow:
    window: int
    token: str
    primary_pool: str | None
    frozen_ref: float | None
    frozen_ref_block: int | None
    reopen_ref: float | None
    reopen_ref_block: int | None
    twap_span: float | None          # [start, cutoff]
    twap_last_hour: float | None     # [cutoff - 1h, cutoff]
    gap_bps: float | None            # ln(twap_last_hour / frozen) * 1e4
    reopen_bps: float | None
    tape_error_bps: float | None
    max_abs_gap_bps: float | None    # largest |ln(price/frozen)| over the span, from swap prices
    swaps_span: int
    volume_span_usd: float
    swaps_last_12h: int
    volume_last_12h_usd: float
    alt_247_ref: float | None        # the 24/7 Chainlink feed at the cutoff, when one exists
    void: str | None


def tape_row(w: Window, token: str, pools: list[PoolPath], ref, alt_series=None) -> TapeRow:
    """ref: the token's 24/5 Series. For daily windows the 'frozen' value is the reference at the cutoff."""
    pp = primary_pool(pools, w.start_ms)
    s = ref.at(w.start_ms) if ref else None
    if w.kind == 2 and ref:
        s = ref.at(w.cutoff_ms)
    e = ref.at(w.end_ms) if ref else None
    frozen = ref.price(s) if s else None
    reopen = ref.price(e) if e else None
    twap_span = usd_twap(pp, w.start_ms, w.cutoff_ms) if pp and w.cutoff_ms > w.start_ms else None
    twap_last = usd_twap(pp, w.cutoff_ms - LAST_HOUR, w.cutoff_ms) if pp else None
    n_span = pp.path.count_between(w.start_ms, w.cutoff_ms) if pp else 0
    v_span = volume_usd(pp, w.start_ms, w.cutoff_ms) if pp else 0.0
    n12 = pp.path.count_between(w.cutoff_ms - THIN_LOOKBACK, w.cutoff_ms) if pp else 0
    v12 = volume_usd(pp, w.cutoff_ms - THIN_LOOKBACK, w.cutoff_ms) if pp else 0.0
    max_gap = None
    if pp and frozen:
        f = pp.usd
        path = pp.path
        i, j = path.index_range(w.start_ms, w.cutoff_ms)
        vals = [abs(math.log(path.price[k] * f(path._ts[k]) / frozen)) * 1e4 for k in range(i, j)
                if f(path._ts[k]) and path.price[k] > 0]
        max_gap = max(vals) if vals else None
    void = None
    if frozen is None:
        void = "missing_reference"
    elif pp is None:
        void = "no_pool"
    elif twap_last is None:
        void = "no_dex_price"
    elif n12 < THIN_MIN_SWAPS or v12 < THIN_MIN_USD:
        void = "dex_thin"
    gap = math.log(twap_last / frozen) * 1e4 if (twap_last and frozen) else None
    if void is None and gap is not None and abs(gap) > OUTLIER_BPS:
        void = "dex_price_outlier"
    reo = math.log(reopen / frozen) * 1e4 if (reopen and frozen and e and s and e.block != s.block) else None
    if w.kind == 1 and e is not None and w.reopen_ms is not None and e.ts_ms <= w.reopen_ms:
        reo = None   # no update after the reopen yet: the outcome is not known
    err = (reo - gap) if (reo is not None and gap is not None) else None
    alt = None
    if alt_series is not None:
        u = alt_series.at(w.cutoff_ms)
        alt = alt_series.price(u) if u else None
    return TapeRow(w.id, token, pp.pool_id if pp else None, frozen, s.block if s else None, reopen,
                   e.block if e else None, twap_span, twap_last, gap, reo, err, max_gap, n_span, v_span, n12, v12,
                   alt, void)


def sigma_bps(history: list[TapeRow], before_ms_ids: set[int] | None = None) -> float:
    """Robust spread of the tape error over earlier windows' non-void rows: 1.4826 x the median absolute
    error (equals the standard deviation for normal errors; one broken pool cannot swamp it). The prior
    until SIGMA_MIN_WINDOWS windows exist; never below 25 bps."""
    errs = sorted(abs(r.tape_error_bps) for r in history if r.tape_error_bps is not None and r.void is None)
    windows = {r.window for r in history if r.tape_error_bps is not None and r.void is None}
    if len(windows) < SIGMA_MIN_WINDOWS or not errs:
        return SIGMA_PRIOR_BPS
    n = len(errs)
    med = errs[n // 2] if n % 2 else (errs[n // 2 - 1] + errs[n // 2]) / 2
    return max(25.0, 1.4826 * med)


def baseline(row: TapeRow, sigma: float) -> dict:
    """The DEX-implied probability and point call for one (window, token)."""
    if row.void or row.gap_bps is None:
        return {"p": 0.5, "ret_bps": None, "void": row.void or "no_gap", "sigma_bps": sigma}
    p = phi(row.gap_bps / sigma)
    p = min(P_CLIP[1], max(P_CLIP[0], p))
    return {"p": round(p, 4), "ret_bps": round(row.gap_bps, 1), "void": None, "sigma_bps": round(sigma, 2)}


def tape_stats(rows: list[dict]) -> dict:
    """Summary of the closed-span tape (tape.csv rows as strings) over non-void rows with both a gap and a
    reopen move: the one definition behind every published tape median (site overview, launch post, report)."""
    closed = [r for r in rows if r["kind"] == "1" and not r["void"] and r["reopen_bps"] and r["gap_bps"]]
    if not closed:
        return {}
    reo = [abs(float(r["reopen_bps"])) for r in closed]
    err = [abs(float(r["tape_error_bps"])) for r in closed]
    gap = [abs(float(r["gap_bps"])) for r in closed]
    same_dir = [r for r in closed if abs(float(r["gap_bps"])) >= 10 and abs(float(r["reopen_bps"])) >= 10]
    agree = sum(1 for r in same_dir if (float(r["gap_bps"]) > 0) == (float(r["reopen_bps"]) > 0))
    closer = sum(1 for r in closed if abs(float(r["tape_error_bps"])) < abs(float(r["reopen_bps"])))
    return {"n": len(closed), "windows": len({r["window"] for r in closed}),
            "median_reopen_bps": statistics.median(reo), "median_gap_bps": statistics.median(gap),
            "median_error_bps": statistics.median(err), "max_reopen_bps": max(reo),
            "direction_agree": agree, "direction_n": len(same_dir), "dex_closer_than_frozen": closer}
