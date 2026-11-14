"""Scorer on synthetic feed series: a normal day, a frozen closed span, a holiday span, a stale feed, a
multiplier event inside a window, a feed phase change, late and repeated commits."""

from datetime import date

import pytest

from callrec import commits, score
from callrec.calendar import windows_between
from callrec.commits import Call, Record
from callrec.feeds import Series, Update

T = "0xb20000000000000000000078ee7ce2fe4908108c"
U = "0xb2000000000000000000001e800a7f5189430cd0"
HOUR = 3_600_000


def _ws():
    ws = windows_between(date(2026, 11, 9), date(2026, 11, 30))
    return {w.label.split(" ")[0] + ":" + w.label.split(" ")[1]: w for w in ws}


def series(points, agg="0xagg1"):
    return Series([Update(ts, i + 1, int(v * 1e8), i + 1, agg, ts // 1000) for i, (ts, v) in enumerate(points)])


def rec(committer, w, data, ts_ms, i=0):
    return Record(committer, w.id, 1, data, 1000 + i, ts_ms, f"0xtx{committer}{i}", i)


def test_closed_span_outcome_and_frozen_value():
    w = _ws()["closed:2026-11-13"]
    s = series([(w.start_ms - HOUR, 100.0), (w.reopen_ms + 5 * 60_000, 103.0)])
    oc = score.outcome_for(T, w, s, [], 26 * HOUR)
    assert oc.void is None and oc.outcome == 1 and oc.start == 100.0 and oc.end == 103.0
    assert round(oc.ret_bps) == round(10_000 * 0.0295588)


def test_closed_span_without_update_after_reopen_is_void():
    w = _ws()["closed:2026-11-13"]
    s = series([(w.start_ms - HOUR, 100.0)])
    assert score.outcome_for(T, w, s, [], 26 * HOUR).void == "no_update_after_reopen"


def test_daily_stale_and_unchanged_and_event_voids():
    w = _ws()["daily:2026-11-17"]
    stale = series([(w.start_ms - 30 * HOUR, 100.0), (w.start_ms - 29 * HOUR, 101.0)])
    assert score.outcome_for(T, w, stale, [], 26 * HOUR).void == "stale_reference"
    same = series([(w.start_ms - HOUR, 100.0), (w.end_ms - HOUR, 100.0)])
    assert score.outcome_for(T, w, same, [], 26 * HOUR).void == "unchanged_reference"
    ok = series([(w.start_ms - HOUR, 100.0), (w.end_ms - HOUR, 99.0)])
    assert score.outcome_for(T, w, ok, ["UIMultiplierUpdated"], 26 * HOUR).void.startswith("token_event")
    assert score.outcome_for(T, w, ok, [], 26 * HOUR).outcome == 0


def test_phase_change_inside_window_uses_latest_update_of_any_aggregator():
    w = _ws()["daily:2026-11-17"]
    s = Series([Update(w.start_ms - HOUR, 1, 100 * 10**8, 50, "0xold", 0),
                Update(w.end_ms - HOUR, 2, 102 * 10**8, 1, "0xnew", 0)])  # new phase restarts round ids
    assert score.outcome_for(T, w, s, [], 26 * HOUR).outcome == 1


def test_holiday_span_window_exists_and_thanksgiving_has_no_daily():
    ws = windows_between(date(2026, 11, 23), date(2026, 11, 30))
    labels = [w.label for w in ws]
    assert any(lbl.startswith("closed 2026-11-25 (Wed) -> 2026-11-26 (Thu)") for lbl in labels)
    assert not any(lbl.startswith("daily 2026-11-26") for lbl in labels)


def test_first_record_counts_missing_token_is_half_late_record_not_scored():
    w = _ws()["daily:2026-11-17"]
    outcomes = {T: score.TokenOutcome(T, 100, 101, 1, 2, 1, None, 99.5),
                U: score.TokenOutcome(U, 100, 99, 1, 2, 0, None, -100.5)}
    a1 = commits.encode_calls([Call(T, 9000, 80)])                 # leaves U out -> 0.5
    a2 = commits.encode_calls([Call(T, 1000, None), Call(U, 1000, None)])   # later: not scored
    late = commits.encode_calls([Call(T, 10000, None)])
    recs = [rec("0xa", w, a1, w.cutoff_ms - 10, 0), rec("0xa", w, a2, w.cutoff_ms - 5, 1),
            rec("0xb", w, late, w.cutoff_ms + 1, 2)]
    fws = score.score_window(w, [T, U], outcomes, recs, {T: 0.5, U: 0.5}, commits.decode_calls)
    a = next(f for f in fws if f.committer == "0xa")
    assert [round(p["brier"], 4) for p in a.pairs] == [0.01, 0.25]
    assert a.pairs[0]["point_sq_err"] == pytest.approx((80 - 99.5) ** 2)
    b = next(f for f in fws if f.committer == "0xb")
    assert b.late and not b.pairs


def test_summary_ranks_by_lower_bound_only_after_minimum_windows():
    fws = []
    for i in range(6):
        fw = score.ForecasterWindow("0xgood", 220261100 + i)
        fw.pairs = [{"token": T, "p": 0.8, "o": 1, "brier": 0.04, "baseline_p": 0.5, "baseline_brier": 0.25,
                     "given": True}, {"token": U, "p": 0.6, "o": 1, "brier": 0.16, "baseline_p": 0.5,
                     "baseline_brier": 0.25, "given": True}]
        fws.append(fw)
    short = score.ForecasterWindow("0xnew", 220261100)
    short.pairs = [{"token": T, "p": 1.0, "o": 1, "brier": 0.0, "baseline_p": 0.5, "baseline_brier": 0.25,
                    "given": True}]
    fws.append(short)
    summ = score.summarize(fws, min_windows=5)
    assert summ["0xgood"]["ranked"] and not summ["0xnew"]["ranked"]
    assert summ["0xgood"]["skill_vs_50"] == pytest.approx(1 - 0.10 / 0.25)
    ranked = score.rank(summ)
    assert ranked[0]["committer"] == "0xgood" and ranked[0]["rank"] == 1 and ranked[1]["rank"] is None


def test_half_everywhere_scores_zero_against_fifty():
    fw = score.ForecasterWindow("0xnull", 1)
    fw.pairs = [{"token": T, "p": 0.5, "o": 1, "brier": 0.25, "baseline_p": 0.5, "baseline_brier": 0.25,
                 "given": True}]
    assert score.summarize([fw])["0xnull"]["skill_vs_50"] == 0
