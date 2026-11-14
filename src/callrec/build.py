"""The build: every published file as a pure function of data/raw, config/ and as_of (METHODS.md).

`build(as_of_ms)` returns {relative path: bytes}. Floats are rounded before serialisation so that the
same inputs give the same bytes on any platform. Nothing here reads the network.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from . import METHODS_VERSION, commits, config, feeds, registry, store
from . import score as scoremod
from . import tape as tapemod
from .calendar import Window, et, windows_between

START_DATE = date(2026, 8, 24)
DAY_MS = 86_400_000
TOKEN_EVENT_NAMES = ("UIMultiplierUpdated", "MultiplierUpdated", "UIMultiplierUpdateCancelled",
                     "Announcement", "EndAnnouncement", "Paused", "Unpaused")


def r(x, nd=6):
    if x is None:
        return None
    if isinstance(x, float):
        if not math.isfinite(x):
            return None
        return round(x, nd)
    return x


def jbytes(obj) -> bytes:
    return (json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def cbytes(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue().encode("utf-8")


# --- inputs ------------------------------------------------------------------------------------------
class Inputs:
    def __init__(self, as_of_ms: int):
        self.as_of_ms = as_of_ms
        self.tokens = registry.load()
        self.by_addr = {t["address"]: t for t in self.tokens["tokens"]}
        self.feed_cfg = feeds.load()
        self.series = feeds.load_series(self.feed_cfg, [x for x in store.read("feeds") if x["ts_ms"] <= as_of_ms])
        self.feed_of: dict[str, dict] = {}       # token -> 24/5 feed config
        self.alt_of: dict[str, dict] = {}        # token -> 24/7 feed config
        for f in self.feed_cfg:
            if not f.get("token"):
                continue
            (self.feed_of if f["kind"] == "24/5" else self.alt_of)[f["token"]] = f
        names = {v: k for k, v in config.chain()["b20_events"].items()}
        self.token_events: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for row in store.read("b20", to_ms=as_of_ms):
            name = names.get(row["topics"][0]) if row["topics"] else None
            if name in TOKEN_EVENT_NAMES:
                self.token_events[row["address"]].append((row["ts_ms"], name))
                eff = _effective_at_ms(name, row)
                if eff is not None:
                    self.token_events[row["address"]].append((eff, name + ":effective"))
        self.house = _house()
        self.records = _records(as_of_ms)
        from . import pools as poolsmod
        self.pool_paths = poolsmod.load_paths(as_of_ms)   # token -> [PoolPath]

    def ref(self, token: str):
        f = self.feed_of.get(token)
        return self.series.get(f["proxy"]) if f else None

    def alt(self, token: str):
        f = self.alt_of.get(token)
        return self.series.get(f["proxy"]) if f else None


def _effective_at_ms(name: str, row: dict) -> int | None:
    """UIMultiplierUpdated carries three uint256 values; the one that reads as a Unix time in seconds
    (between 2020 and 2100) is the scheduled effective time."""
    if name != "UIMultiplierUpdated":
        return None
    from .abi import words
    vals = [int(t, 16) for t in row["topics"][1:]] + words(row["data"])
    ts = [v for v in vals if 1_577_836_800 <= v <= 4_102_444_800]
    return ts[0] * 1000 if ts else None


def _house() -> dict[str, str]:
    import yaml
    d = yaml.safe_load((config.config_dir() / "house.yaml").read_text(encoding="utf-8"))
    return {w["address"].lower(): w["role"] for w in d["wallets"]}


def _records(as_of_ms: int) -> list[commits.Record]:
    out = []
    for row in store.read("ledger", to_ms=as_of_ms):
        if row["topics"] and row["topics"][0] == commits.COMMITTED_TOPIC:
            out.append(commits.decode_committed(row))
    return sorted(out, key=lambda x: (x.block, x.log_index))


# --- per-window computations ---------------------------------------------------------------------------
def slate(inp: Inputs, w: Window) -> list[str]:
    out = []
    for token, f in sorted(inp.feed_of.items()):
        s = inp.series.get(f["proxy"])
        if s and s.between(w.start_ms - 7 * DAY_MS, w.start_ms):
            out.append(token)
    return out


def events_in(inp: Inputs, token: str, w: Window) -> list[str]:
    return [n for ts, n in inp.token_events.get(token, []) if w.start_ms <= ts <= w.end_ms]


def build(as_of_ms: int, inp: Inputs | None = None) -> dict[str, bytes]:
    inp = inp or Inputs(as_of_ms)
    as_of_date = datetime.fromtimestamp(as_of_ms / 1000, UTC).date()
    all_windows = windows_between(START_DATE, as_of_date + timedelta(days=8))
    ended = [w for w in all_windows if w.end_ms <= as_of_ms]
    upcoming = [w for w in all_windows if w.end_ms > as_of_ms][:6]
    stale_ms = 26 * 3_600_000
    files: dict[str, bytes] = {}

    tape_rows: list[tapemod.TapeRow] = []
    window_docs, outcome_rows, fws_all = [], [], []
    hist: dict[int, list[tapemod.TapeRow]] = {1: [], 2: []}
    baselines: dict[tuple[int, str], dict] = {}
    by_window = defaultdict(list)
    for rec in inp.records:
        if rec.schema == commits.SCHEMA_CALLS:
            by_window[rec.window].append(rec)

    for w in ended:
        sl = slate(inp, w)
        sigma = tapemod.sigma_bps(hist[w.kind])
        outs, base_p, rows_w = {}, {}, []
        for k in sl:
            oc = scoremod.outcome_for(k, w, inp.ref(k), events_in(inp, k, w), stale_ms)
            outs[k] = oc
            tr = tapemod.tape_row(w, k, inp.pool_paths.get(k, []), inp.ref(k), inp.alt(k))
            rows_w.append(tr)
            b = tapemod.baseline(tr, sigma)
            baselines[(w.id, k)] = b
            base_p[k] = b["p"]
            sym = inp.by_addr.get(k, {}).get("symbol")
            outcome_rows.append([w.id, w.label, sym, k, r(oc.start), oc.start_block, r(oc.end), oc.end_block,
                                 oc.outcome, oc.void, r(oc.ret_bps, 2), b["p"], b["ret_bps"], b["void"]])
        tape_rows += rows_w
        hist[w.kind] += rows_w
        fws = scoremod.score_window(w, sl, outs, by_window.get(w.id, []), base_p, commits.decode_calls)
        fws_all += fws
        window_docs.append({**w.as_dict(), "start_et": et(w.start_ms), "cutoff_et": et(w.cutoff_ms),
                            "end_et": et(w.end_ms), "slate": sl, "sigma_bps": r(sigma, 2),
                            "scored_tokens": sum(1 for o in outs.values() if o.outcome is not None),
                            "forecasters": len([f for f in fws if f.pairs])})

    summary = scoremod.summarize(fws_all)
    board = scoremod.rank(summary)
    for s in board:
        s["house_role"] = inp.house.get(s["committer"].lower())
        for k in ("brier", "baseline_brier", "skill_vs_dex", "skill_vs_50", "edge_mean", "edge_lcb",
                  "calls_given_share", "point_rmse_bps", "persistence_rmse_bps"):
            s[k] = r(s[k], 6)

    # forecaster pages: probabilities only for resolved windows (all windows here are ended)
    per_forecaster = defaultdict(list)
    for fw in fws_all:
        per_forecaster[fw.committer].append({
            "window": fw.window, "record_tx": fw.record_tx, "late": fw.late,
            "pairs": [{k: (r(v, 6) if isinstance(v, float) else v) for k, v in p.items()} for p in fw.pairs]})
    for c, items in per_forecaster.items():
        files[f"forecasters/{c.lower()}.json"] = jbytes({"committer": c.lower(),
                                                        "house_role": inp.house.get(c.lower()),
                                                        "windows": sorted(items, key=lambda x: x["window"])})

    # open windows: who committed (never what)
    open_docs = []
    for w in upcoming:
        recs = by_window.get(w.id, [])
        committed = sorted({x.committer.lower() for x in recs if x.ts_ms <= w.cutoff_ms})
        open_docs.append({**w.as_dict(), "start_et": et(w.start_ms), "cutoff_et": et(w.cutoff_ms),
                          "end_et": et(w.end_ms), "slate": slate(inp, w), "committed": committed,
                          "open_for_records": w.cutoff_ms > as_of_ms})

    usage = _usage(inp, as_of_ms)
    missing = _house_missing(inp, ended)

    files["windows.json"] = jbytes({"windows": window_docs})
    files["open.json"] = jbytes({"windows": open_docs})
    files["outcomes.csv"] = cbytes(
        ["window", "label", "symbol", "token", "ref_start", "ref_start_block", "ref_end", "ref_end_block",
         "outcome", "void", "realised_bps", "dex_implied_p", "dex_implied_ret_bps", "dex_void"], outcome_rows)
    files["leaderboard.json"] = jbytes({"min_windows": scoremod.MIN_WINDOWS, "forecasters": board})
    files["tape.csv"] = cbytes(
        ["window", "kind", "symbol", "token", "primary_pool", "frozen_ref", "frozen_ref_block", "reopen_ref",
         "reopen_ref_block", "twap_span", "twap_last_hour", "gap_bps", "reopen_bps", "tape_error_bps",
         "max_abs_gap_bps", "swaps_span", "volume_span_usd", "swaps_last_12h", "volume_last_12h_usd",
         "alt_247_ref", "void"],
        [[t.window, t.window // 100_000_000, inp.by_addr.get(t.token, {}).get("symbol"), t.token, t.primary_pool,
          r(t.frozen_ref), t.frozen_ref_block, r(t.reopen_ref), t.reopen_ref_block, r(t.twap_span), r(t.twap_last_hour),
          r(t.gap_bps, 2), r(t.reopen_bps, 2), r(t.tape_error_bps, 2), r(t.max_abs_gap_bps, 2), t.swaps_span,
          r(t.volume_span_usd, 2), t.swaps_last_12h, r(t.volume_last_12h_usd, 2), r(t.alt_247_ref), t.void]
         for t in tape_rows])
    files["usage.json"] = jbytes(usage)
    files["house_checks.json"] = jbytes({"house_commit_missing": missing})
    files["feed_hours.json"] = jbytes(feed_hours(inp, ended))

    from . import coverage
    absorb = None
    try:
        absorb = coverage.absorb_table(inp, as_of_ms)
    except FileNotFoundError:
        absorb = None
    if absorb is not None:
        files["absorb.json"] = jbytes(_round_tree(absorb))
    files["coverage_scores.json"] = jbytes(_round_tree(coverage_scores(inp, ended)))
    files["baselines.json"] = jbytes(_round_tree(baseline_summary(outcome_rows)))
    for token in sorted(inp.feed_of):
        sym_ = inp.by_addr.get(token, {}).get("symbol") or token
        files[f"feed/{sym_}.json"] = jbytes(_round_tree(token_feed(inp, token, as_of_ms, absorb)))
    files["backtest.csv"] = backtest_csv(inp, as_of_ms)
    from . import volume
    vq = []
    for token in sorted(inp.feed_of):
        pps = inp.pool_paths.get(token, [])
        if not pps:
            continue
        start_ms = int(datetime(START_DATE.year, START_DATE.month, START_DATE.day, tzinfo=UTC).timestamp() * 1000)
        for label, lo in (("since_2026-08-24", start_ms), ("last_7_days", as_of_ms - 7 * DAY_MS)):
            res = volume.shares_from_paths(sorted(pps, key=lambda p: p.pool_id), lo, as_of_ms)
            vq.append({"token": token, "symbol": inp.by_addr.get(token, {}).get("symbol"), "period": label,
                       **{k: (r(v, 6) if isinstance(v, float) else v) for k, v in res.items()}})
    files["volume_quality.json"] = jbytes({"router_like_threshold": volume.ROUTER_LIKE, "rows": vq})
    from . import pools as poolsmod
    lk = (poolsmod.raw_config().get("lookalikes") or {})
    files["lookalikes.json"] = jbytes({
        "flag": "R1_lookalike_symbol", "rule": lk.get("rule"),
        "tokens": [{"address": t["address"].lower(), "symbol": t.get("symbol"), "name": t.get("name"),
                    "resembles": t.get("resembles", []), "match": t.get("match", []), "seen_in": t.get("seen_in", []),
                    "R1_lookalike_symbol": True}
                   for t in sorted(lk.get("tokens", []), key=lambda t: t["address"].lower())
                   if t["address"].lower() not in inp.by_addr]})
    return files


def baseline_summary(outcome_rows: list[list]) -> dict:
    """The DEX-implied baseline scored on every resolved (window, token) since Aug 24, as if it had been on the
    record: computed from the data, not committed (house records start at the ledger's deployment)."""
    out = {}
    for kind, label in ((1, "closed"), (2, "daily")):
        rows = [x for x in outcome_rows if x[0] // 100_000_000 == kind and x[8] is not None]
        scored = [x for x in rows if x[13] is None]          # DEX baseline not void
        n = len(scored)
        if not n:
            out[label] = {"pairs": 0}
            continue
        brier = sum((x[11] - x[8]) ** 2 for x in scored) / n
        hits = [x for x in scored if x[11] != 0.5]
        hit = sum(1 for x in hits if (x[11] > 0.5) == (x[8] == 1)) / len(hits) if hits else None
        out[label] = {"pairs": n, "windows": len({x[0] for x in scored}), "pairs_void_dex": len(rows) - n,
                      "brier": brier, "skill_vs_50": 1 - brier / 0.25,
                      "direction_hit_rate": hit, "direction_pairs": len(hits), "on_the_record": False}
    return out


def coverage_scores(inp: Inputs, ended: list[Window]) -> dict:
    """Every closed window with a house coverage record (schema 2): the committed depth against the depth at
    the same price levels in the first snapshot after the reopen; and, when a token's reopen move is 5% or
    more, the committed liquidation flow against the collateral liquidated in the 24 hours after the reopen."""
    from . import coverage, depthread
    from . import pools as poolsmod
    from .depth import quote_out
    cov_addr = next((a for a, role in inp.house.items() if role == "coverage"), None)
    recs = {x.window: x for x in inp.records if x.schema == commits.SCHEMA_COVERAGE and x.committer.lower() == cov_addr}
    plist = {p.id: p for p in poolsmod.load_pools()}
    snaps = depthread.snapshots()
    out = []
    for w in ended:
        rec = recs.get(w.id)
        if w.kind != 1 or rec is None or rec.ts_ms > w.cutoff_ms:
            continue
        try:
            blk, entries = commits.decode_coverage(rec.data)
        except ValueError:
            out.append({"window": w.id, "status": "undecodable_record", "tx": rec.tx})
            continue
        after = next((s for s in snaps if w.reopen_ms <= s["ts_ms"] <= w.reopen_ms + 2 * 3_600_000), None)
        liq = coverage.liquidations_between(w.reopen_ms, w.reopen_ms + 24 * 3_600_000)
        for e in entries:
            ref = inp.ref(e.token)
            frozen = ref.price(ref.at(w.start_ms)) if ref else None
            reopen = ref.price(ref.at(w.end_ms)) if ref else None
            move = (reopen / frozen - 1) if (frozen and reopen) else None
            row = {"window": w.id, "token": e.token, "symbol": inp.by_addr.get(e.token, {}).get("symbol"),
                   "record_tx": rec.tx, "record_block": rec.block, "snapshot_block_committed": blk,
                   "reopen_move_pct": move * 100 if move is not None else None}
            for i, s in enumerate(("5", "10", "20")):
                committed = e.depth_usd[i]
                at_reopen = None
                if after is not None and frozen:
                    a = frozen * (1 - int(s) / 100)
                    tot = 0.0
                    for pid, raw in after["pools"].items():
                        p = plist.get(pid)
                        if p is None or p.token != e.token:
                            continue
                        st = depthread.state_from_raw(p, raw)
                        f = poolsmod.usd_factor(p.quote, inp.as_of_ms)(after["ts_ms"])
                        if f:
                            tot += quote_out(st, min(a, st.token_price()), a * 0.95) * f
                    at_reopen = tot
                row[f"depth_committed_{s}"] = committed
                row[f"depth_at_reopen_{s}"] = at_reopen
                row[f"depth_change_pct_{s}"] = ((at_reopen / committed - 1) * 100) if (committed and at_reopen is not None) else None
                row[f"liquidation_flow_committed_{s}"] = e.liquidation_flow_usd[i]
            if move is not None and abs(move) >= 0.05:
                row["liquidated_usd_24h_after_reopen"] = liq.get(e.token, 0.0)
            row["reopen_snapshot_block"] = after["block"] if after else None
            out.append(row)
    return {"rows": out}


def _round_tree(x):
    if isinstance(x, float):
        return r(x, 6)
    if isinstance(x, dict):
        return {str(k): _round_tree(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_round_tree(v) for v in x]
    return x


def token_feed(inp: Inputs, token: str, as_of_ms: int, absorb: dict | None) -> dict:
    """The per-token machine-readable record (METHODS.md section 9). Read-only data; no routing, no links."""
    ref = inp.ref(token)
    u = ref.at(as_of_ms) if ref else None
    row = next((x for x in (absorb or {}).get("tokens", []) if x["token"] == token), None)
    from .coverage import _in_closed
    closed = _in_closed(as_of_ms)
    stale_h = (as_of_ms - u.ts_ms) / 3_600_000 if u else None
    flags = list(row["flags"]) if row else []
    if stale_h is not None and stale_h > 26 and not closed and "S1_stale_reference" not in flags:
        flags.append("S1_stale_reference")
    tier = row["tier"] if row else ("stale" if "S1_stale_reference" in flags else "insufficient_data")
    return {
        "schema": "callrec-token-feed/v1",
        "methods_version": METHODS_VERSION,
        "token": token,
        "symbol": inp.by_addr.get(token, {}).get("symbol"),
        "official": token in inp.by_addr,
        "as_of_ms": as_of_ms,
        "reference": {"value": ref.price(u) if u else None, "updated_ms": u.ts_ms if u else None,
                      "block": u.block if u else None, "hours_since_update": stale_h,
                      "frozen_now": closed, "feed_proxy": inp.feed_of[token]["proxy"]},
        "tier": tier,
        "flags": [{"id": f, "value": True, "evidence": "absorb.json" if row else "feeds"} for f in flags],
        "depth": None if not row else {"move_1pct_usd": row["move_1pct_usd"], "move_2pct_usd": row["move_2pct_usd"],
                                       "impact_10k_bps": row["impact_10k_bps"], "impact_100k_bps": row["impact_100k_bps"],
                                       "snapshot_block": (absorb or {}).get("block")},
        "coverage": None if not row else {"absorb_5pct_below_usd": row["absorb_5pct_below_usd"],
                                          "liquidation_flow_usd": row["liquidation_flow_usd"],
                                          "underwater_debt_usd": row["underwater_debt_usd"]},
    }


def backtest_csv(inp: Inputs, as_of_ms: int) -> bytes:
    """One row per token per calendar day at 20:00 ET: the reference value and its age, the primary pool's
    USD price and its gap to the reference, and whether the reference was frozen then."""
    from zoneinfo import ZoneInfo

    from .coverage import _in_closed
    tz = ZoneInfo("America/New_York")
    rows = []
    d = START_DATE
    end = datetime.fromtimestamp(as_of_ms / 1000, UTC).date()
    while d <= end:
        t = int(datetime(d.year, d.month, d.day, 20, 0, tzinfo=tz).timestamp() * 1000)
        if t > as_of_ms:
            break
        closed = _in_closed(t)
        for token in sorted(inp.feed_of):
            ref = inp.ref(token)
            u = ref.at(t) if ref else None
            pp = tapemod.primary_pool(inp.pool_paths.get(token, []), t)
            px = None
            if pp is not None:
                tick = pp.path.at(t)
                f = pp.usd(t)
                px = tick.price * f if (tick and f) else None
            refv = ref.price(u) if u else None
            gap = math.log(px / refv) * 1e4 if (px and refv) else None
            rows.append([d.isoformat(), inp.by_addr.get(token, {}).get("symbol"), token, r(refv),
                         r((t - u.ts_ms) / 3_600_000, 2) if u else None, int(closed), r(px), r(gap, 2),
                         pp.pool_id if pp else None])
        d += timedelta(days=1)
    return cbytes(["date", "symbol", "token", "ref_value_2000_et", "ref_age_hours", "reference_frozen",
                   "primary_pool_usd", "gap_bps", "primary_pool"], rows)


def _usage(inp: Inputs, as_of_ms: int) -> dict:
    ext = [x for x in inp.records if x.committer.lower() not in inp.house]
    house = [x for x in inp.records if x.committer.lower() in inp.house]
    by_day = defaultdict(lambda: {"records": 0, "wallets": set()})
    for x in ext:
        d = datetime.fromtimestamp(x.ts_ms / 1000, UTC).strftime("%Y-%m-%d")
        by_day[d]["records"] += 1
        by_day[d]["wallets"].add(x.committer.lower())
    counts = defaultdict(int)
    for x in ext:
        counts[x.committer.lower()] += 1
    total = sum(counts.values())
    top_share = (max(counts.values()) / total) if total else None
    return {
        "external_records": len(ext),
        "external_wallets": len(counts),
        "external_transactions": len({x.tx for x in ext}),
        "house_records_excluded": len(house),
        "top_wallet_share_of_external_records": r(top_share, 4),
        "by_day": [{"date": d, "records": v["records"], "wallets": len(v["wallets"])} for d, v in sorted(by_day.items())],
    }


def _house_missing(inp: Inputs, ended: list[Window]) -> list[dict]:
    """Closed windows after the mainnet ledger's deployment with an expected house record absent."""
    from . import tx
    try:
        dep = tx.ledger("base")
    except Exception:
        return []
    from .chain import schedule
    dep_ms = schedule().ts_ms(int(dep["block"]))
    got = {(x.committer.lower(), x.window, x.schema) for x in inp.records if x.ts_ms <= _cutoff(x.window, ended)}
    role_addr = {v: k for k, v in inp.house.items()}
    out = []
    for w in ended:
        if w.kind != 1 or w.start_ms < dep_ms:
            continue
        for role, schema in (("null", 1), ("persistence", 1), ("dex_implied", 1), ("coverage", 2)):
            if (role_addr[role], w.id, schema) not in got:
                out.append({"window": w.id, "label": w.label, "role": role, "schema": schema,
                            "house_commit_missing": True, "evidence": f"no Committed event from {role_addr[role]} "
                            f"for window {w.id} schema {schema} at or before {et(w.cutoff_ms)}"})
    return out


def _cutoff(wid: int, ended: list[Window]) -> int:
    for w in ended:
        if w.id == wid:
            return w.cutoff_ms
    return 2 ** 62


def feed_hours(inp: Inputs, ended: list[Window]) -> dict:
    """Measured: per closed window and 24/5 feed, the last update before the span start and the first
    after the reopen; plus every gap between updates longer than 6 hours outside closed spans."""
    rows = []
    closed = [w for w in ended if w.kind == 1]
    for token, f in sorted(inp.feed_of.items()):
        s = inp.series.get(f["proxy"])
        if not s:
            continue
        sym = inp.by_addr.get(token, {}).get("symbol")
        for w in closed:
            last = s.at(w.start_ms)
            inside = s.between(w.start_ms + 1, w.reopen_ms)
            after = s.between(w.reopen_ms + 1, w.reopen_ms + 6 * 3_600_000)
            rows.append({"window": w.id, "symbol": sym, "last_before_start_et": et(last.ts_ms) if last else None,
                         "updates_inside_span": len(inside),
                         "first_after_reopen_et": et(after[0].ts_ms) if after else None,
                         "first_after_reopen_minutes": r((after[0].ts_ms - w.reopen_ms) / 60000, 1) if after else None})
    return {"closed_windows": rows}
