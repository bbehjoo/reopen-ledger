from datetime import date

from callrec import tape
from callrec.calendar import windows_between
from callrec.feeds import Series, Update
from callrec.swaps import Path, Tick

HOUR = 3_600_000


def closed():
    return next(w for w in windows_between(date(2026, 11, 9), date(2026, 11, 20)) if w.kind == 1)


def ref_series(w, frozen=100.0, reopen=104.0):
    return Series([Update(w.start_ms - HOUR, 1, int(frozen * 1e8), 1, "0xa", 0),
                   Update(w.reopen_ms + 60_000, 2, int(reopen * 1e8), 2, "0xa", 0)])


def pool_path(w, prices_every_hour):
    ticks = [Tick(w.start_ms + i * HOUR, 10 + i, 0, p, 500.0, 5.0, True, "0x", "", "")
             for i, p in enumerate(prices_every_hour)]
    return tape.PoolPath("0xpool", Path(ticks), lambda ts: 1.0)


def test_tape_row_gap_and_error():
    w = closed()
    hours = int((w.cutoff_ms - w.start_ms) / HOUR) + 1
    pp = pool_path(w, [100.0] * (hours - 3) + [103.0, 103.0, 103.0])
    r = tape.tape_row(w, "0xtok", [pp], ref_series(w))
    assert r.void is None and r.frozen_ref == 100.0 and r.reopen_ref == 104.0
    assert abs(r.twap_last_hour - 103.0) < 1e-9
    assert abs(r.gap_bps - 295.588) < 0.01
    assert abs(r.tape_error_bps - (392.207 - 295.588)) < 0.01


def test_thin_pool_is_void_and_baseline_falls_back_to_half():
    w = closed()
    pp = pool_path(w, [100.0, 101.0])   # two swaps early in the span, none in the last 12 h
    r = tape.tape_row(w, "0xtok", [pp], ref_series(w))
    assert r.void == "dex_thin"
    b = tape.baseline(r, 150.0)
    assert b["p"] == 0.5 and b["ret_bps"] is None


def test_baseline_probability_and_clip():
    w = closed()
    hours = int((w.cutoff_ms - w.start_ms) / HOUR) + 1
    r = tape.tape_row(w, "0xtok", [pool_path(w, [103.0] * hours)], ref_series(w))
    b = tape.baseline(r, 150.0)
    assert 0.94 < b["p"] <= 0.95   # gap ~296 bps over sigma 150 -> Phi(1.97) = 0.976, clipped to 0.95
    r2 = tape.tape_row(w, "0xtok", [pool_path(w, [100.2] * hours)], ref_series(w))
    assert 0.5 < tape.baseline(r2, 150.0)["p"] < 0.6


def test_sigma_prior_until_enough_windows():
    w = closed()
    hours = int((w.cutoff_ms - w.start_ms) / HOUR) + 1
    r = tape.tape_row(w, "0xtok", [pool_path(w, [103.0] * hours)], ref_series(w))
    assert tape.sigma_bps([r]) == tape.SIGMA_PRIOR_BPS
