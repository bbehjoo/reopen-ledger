"""The scorer (METHODS.md section 5). Pure functions of the raw store and config; replayable.

Per window W (ended at or before as_of) and slate token k:
  outcome  o = 1 if ref(W.end) > ref(W.start), 0 if below; the token is void for W when either value is
           missing, the two are equal, the end value is stale, or a multiplier or pause event falls in W
           (void reasons are published per token).
  Brier    (p - o)^2 for each forecaster that committed to W before its cutoff (first record counts; a slate
           token it left out scores as p = 0.5).
Per forecaster, over the windows it committed to:
  brier        mean Brier over its scored (window, token) pairs
  skill_vs_dex 1 - brier / brier of the DEX-implied baseline on the same pairs
  skill_vs_50  1 - brier / 0.25
  edge_lcb     lower 95% one-sided bound of the per-window mean Brier advantage over the DEX-implied
               baseline (mean - 1.645 * sd / sqrt(n)); ranking key once n >= min_windows
Point calls (ret_bps given) also get the squared error of the log return in basis points, against the
persistence point call (0).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .calendar import Window

MIN_WINDOWS = 5
Z_ONE_SIDED_95 = 1.645


@dataclass
class TokenOutcome:
    token: str
    start: float | None
    end: float | None
    start_block: int | None
    end_block: int | None
    outcome: int | None
    void: str | None
    ret_bps: float | None


@dataclass
class ForecasterWindow:
    committer: str
    window: int
    pairs: list[dict] = field(default_factory=list)   # per token: p, o, brier, baseline_brier
    record_tx: str | None = None
    late: bool = False


def outcome_for(token: str, w: Window, series, events_in_window: list[str], stale_after_ms: int) -> TokenOutcome:
    s = series.at(w.start_ms) if series else None
    e = series.at(w.end_ms) if series else None
    void = None
    if s is None or e is None:
        void = "missing_reference"
    elif events_in_window:
        void = "token_event_in_window:" + ",".join(sorted(set(events_in_window)))
    elif w.reopen_ms is not None and e.ts_ms <= w.reopen_ms:
        void = "no_update_after_reopen"
    elif w.reopen_ms is None and w.end_ms - e.ts_ms > stale_after_ms:
        void = "stale_reference"
    elif e.answer == s.answer:
        void = "unchanged_reference"
    o = None if void else (1 if e.answer > s.answer else 0)
    ret = None
    if s is not None and e is not None and s.answer > 0 and e.answer > 0:
        ret = math.log(e.answer / s.answer) * 1e4
    return TokenOutcome(token, series.price(s) if s else None, series.price(e) if e else None,
                        s.block if s else None, e.block if e else None, o, void, ret)


def brier(p: float, o: int) -> float:
    return (p - o) ** 2


def score_window(w: Window, slate: list[str], outcomes: dict[str, TokenOutcome],
                 records: list, baseline: dict[str, float], decode) -> list[ForecasterWindow]:
    """records: schema-1 Records for window w (any committer), in chain order."""
    first: dict[str, object] = {}
    late: dict[str, object] = {}
    for r in records:
        if r.ts_ms <= w.cutoff_ms:
            first.setdefault(r.committer, r)
        else:
            late.setdefault(r.committer, r)
    out = []
    for committer, r in first.items():
        try:
            calls = {c.token: c for c in decode(r.data)}
        except ValueError:
            calls = {}
        fw = ForecasterWindow(committer, w.id, record_tx=r.tx)
        for k in slate:
            oc = outcomes.get(k)
            if oc is None or oc.outcome is None:
                continue
            c = calls.get(k)
            p = c.p_up_bps / 10_000 if c else 0.5
            b = baseline.get(k, 0.5)
            pair = {"token": k, "p": p, "o": oc.outcome, "brier": brier(p, oc.outcome),
                    "baseline_p": b, "baseline_brier": brier(b, oc.outcome), "given": c is not None}
            if c is not None and c.ret_bps is not None and oc.ret_bps is not None:
                pair["point_sq_err"] = (c.ret_bps - oc.ret_bps) ** 2
                pair["persistence_sq_err"] = oc.ret_bps ** 2
            fw.pairs.append(pair)
        out.append(fw)
    for committer, r in late.items():
        if committer not in first:
            out.append(ForecasterWindow(committer, w.id, record_tx=r.tx, late=True))
    return out


def summarize(fws: list[ForecasterWindow], min_windows: int = MIN_WINDOWS) -> dict[str, dict]:
    by: dict[str, list[ForecasterWindow]] = defaultdict(list)
    for fw in fws:
        by[fw.committer].append(fw)
    out = {}
    for c, items in by.items():
        scored = [fw for fw in items if fw.pairs]
        pairs = [p for fw in scored for p in fw.pairs]
        n_pairs = len(pairs)
        bs = sum(p["brier"] for p in pairs) / n_pairs if n_pairs else None
        bb = sum(p["baseline_brier"] for p in pairs) / n_pairs if n_pairs else None
        per_window = [sum(p["baseline_brier"] - p["brier"] for p in fw.pairs) / len(fw.pairs) for fw in scored]
        n = len(per_window)
        mean = sum(per_window) / n if n else None
        sd = math.sqrt(sum((x - mean) ** 2 for x in per_window) / (n - 1)) if n > 1 else None
        lcb = mean - Z_ONE_SIDED_95 * sd / math.sqrt(n) if (sd is not None and n >= 2) else None
        pts = [p for p in pairs if "point_sq_err" in p]
        out[c] = {
            "committer": c,
            "windows_committed": len(items),
            "windows_scored": n,
            "windows_late_only": sum(1 for fw in items if fw.late),
            "pairs_scored": n_pairs,
            "calls_given_share": (sum(1 for p in pairs if p["given"]) / n_pairs) if n_pairs else None,
            "brier": bs,
            "baseline_brier": bb,
            "skill_vs_dex": (1 - bs / bb) if (bs is not None and bb) else None,
            "skill_vs_50": (1 - bs / 0.25) if bs is not None else None,
            "edge_mean": mean,
            "edge_lcb": lcb,
            "ranked": n >= min_windows and lcb is not None,
            "point_pairs": len(pts),
            "point_rmse_bps": math.sqrt(sum(p["point_sq_err"] for p in pts) / len(pts)) if pts else None,
            "persistence_rmse_bps": math.sqrt(sum(p["persistence_sq_err"] for p in pts) / len(pts)) if pts else None,
        }
    return out


def rank(summary: dict[str, dict]) -> list[dict]:
    ranked = sorted((s for s in summary.values() if s["ranked"]), key=lambda s: (-s["edge_lcb"], s["committer"]))
    rest = sorted((s for s in summary.values() if not s["ranked"]), key=lambda s: (-s["windows_scored"], s["committer"]))
    for i, s in enumerate(ranked, 1):
        s["rank"] = i
    for s in rest:
        s["rank"] = None
    return ranked + rest
