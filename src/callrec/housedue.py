"""Which house records are due now (METHODS.md section 7), and sending them. It may run as often as a
scheduler likes: each record is sent at most once (housecommit.commit reads the chain first), and a record
whose slot has passed is never sent late.

Slots (US Eastern):
  closed window   null, persistence: from the span start to the cutoff
                  dex_implied: the 2 hours before the cutoff
                  coverage (schema 2): the 2 hours after the span start
  daily window    null, persistence: the 12 hours before the cutoff
                  dex_implied: the hour before the cutoff
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from . import commits, housecommit
from .calendar import Window, windows_between

HOUR = 3_600_000


def due_slots(now_ms: int) -> list[tuple[Window, str, int]]:
    today = datetime.fromtimestamp(now_ms / 1000, UTC).date()
    out = []
    for w in windows_between(today - timedelta(days=4), today + timedelta(days=4)):
        if now_ms >= w.cutoff_ms:
            continue
        if w.kind == commits.KIND_WEEKEND:
            if w.start_ms <= now_ms:
                out += [(w, "null", 1), (w, "persistence", 1)]
            if w.cutoff_ms - 2 * HOUR <= now_ms:
                out.append((w, "dex_implied", 1))
            if w.start_ms <= now_ms < w.start_ms + 2 * HOUR:
                out.append((w, "coverage", 2))
        else:
            # null and persistence do not depend on the send time, so their slot is wide enough for a
            # scheduled job that starts hours late; the DEX-implied record reads the last hour's prices
            if w.cutoff_ms - EARLY_HOURS * HOUR <= now_ms:
                out += [(w, "null", 1), (w, "persistence", 1)]
            if w.cutoff_ms - HOUR <= now_ms:
                out.append((w, "dex_implied", 1))
    return out


EARLY_HOURS = 12   # daily windows: null and persistence may be sent from 12 hours before the cutoff


def run_due(network: str, now_ms: int | None = None, dry_run: bool = False, coverage_data=None) -> list[dict]:
    """Send every due house record. coverage_data: callable(window) -> bytes for schema 2 (None: skip)."""
    from .build import Inputs, slate
    from . import tape as tapemod
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if not housecommit.deployed(network):
        return [{"status": "not_deployed", "network": network}]
    slots = due_slots(now_ms)
    if not slots:
        return [{"status": "nothing_due"}]
    inp = Inputs(now_ms)
    results = []
    for w, role, schema in slots:
        try:
            if schema == commits.SCHEMA_CALLS:
                sl = slate(inp, w)
                base = None
                if role == "dex_implied":
                    base = dex_baseline_now(inp, w, now_ms)
                calls = housecommit.calls_for(role, sl, base)
                if not calls:
                    results.append({"status": "skipped_no_calls", "role": role, "window": w.id})
                    continue
                data = commits.encode_calls(calls)
            else:
                if coverage_data is None:
                    results.append({"status": "skipped_no_coverage_data", "role": role, "window": w.id})
                    continue
                data = coverage_data(w)
            results.append(housecommit.commit(network, role, w, w.id, schema, data, dry_run=dry_run, now_ms=now_ms))
        except Exception as e:  # one failed slot never blocks the others
            results.append({"status": "error", "role": role, "window": w.id, "error": f"{type(e).__name__}: {e}"[:300]})
    del tapemod
    return results


def dex_baseline_now(inp, w: Window, now_ms: int) -> dict[str, dict]:
    """The DEX-implied baseline for an open window, as the build will compute it once the window has ended:
    the gap is read over the last hour before the cutoff, so a commit made before the cutoff uses the last
    hour before `now` instead (the committed value is what is scored; the build also reports whether it
    equals the end-of-window baseline)."""
    from . import tape as tapemod
    from .build import START_DATE
    swap_data_fresh(now_ms)
    hist_windows =[x for x in windows_between(START_DATE, datetime.fromtimestamp(now_ms / 1000, UTC).date())
                    if x.kind == w.kind and x.end_ms <= w.start_ms]
    hist = []
    for hw in hist_windows:
        for k in slate(inp, hw):
            hist.append(tapemod.tape_row(hw, k, inp.pool_paths.get(k, []), inp.ref(k), inp.alt(k)))
    sigma = tapemod.sigma_bps(hist)
    shifted = Window(w.id, w.kind, w.label, w.start_ms, min(w.cutoff_ms, now_ms), w.end_ms, w.reopen_ms)
    out = {}
    for k in slate(inp, w):
        tr = tapemod.tape_row(shifted, k, inp.pool_paths.get(k, []), inp.ref(k), inp.alt(k))
        out[k] = tapemod.baseline(tr, sigma)
    return out


STALE_SWAPS_MS = 2 * HOUR


def swap_data_fresh(now_ms: int) -> None:
    """Raise when a swap stream was last read more than 2 hours before `now`: a DEX-implied record is never
    computed from incomplete prices (the slot then errors loudly and the next run retries)."""
    from . import pools, store
    from .chain import schedule
    for s in pools.stream_specs():
        cur = store.cursor(s["stream"])
        if cur is None:
            raise RuntimeError(f"swap stream {s['stream']} is empty; DEX-implied record not computed")
        age = now_ms - schedule().ts_ms(int(cur["to_block"]))
        if age > STALE_SWAPS_MS:
            raise RuntimeError(f"swap stream {s['stream']} ends {age // 60_000} min before now; "
                               "DEX-implied record not computed")


def slate(inp, w):
    from .build import slate as s
    return s(inp, w)
