"""Windows: closed spans (weekends and holidays, kind 1) and daily windows (kind 2), from
config/calendar.yaml, in US Eastern time.

A closed span runs from a session close (Friday 20:00, or 20:00 on the eve of a closed day) to the next
reopen (Sunday 20:00, or 20:00 on a closed day). Its window is dated by the Eastern date the span starts.
  start  = the span's start: the reference value then is the frozen value
  cutoff = reopen - closed_cutoff_minutes_before_reopen
  end    = reopen + closed_settle_minutes: the outcome is the reference value then
A daily window d covers the open session ending at 20:00 on day d:
  start  = 20:00 on the previous calendar day, or the previous closed span's end (after a reopen)
  cutoff = start
  end    = 20:00 on day d
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from . import config
from .commits import KIND_DAILY, KIND_WEEKEND, window_id

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass(frozen=True)
class Window:
    id: int
    kind: int
    label: str          # e.g. "closed 2026-11-13 (Fri) -> 2026-11-15 (Sun)" or "daily 2026-11-16 (Mon)"
    start_ms: int
    cutoff_ms: int
    end_ms: int
    reopen_ms: int | None = None

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "start_ms": self.start_ms,
                "cutoff_ms": self.cutoff_ms, "end_ms": self.end_ms, "reopen_ms": self.reopen_ms}


@cache
def cfg() -> dict:
    return config.load_yaml("calendar.yaml")


def tz() -> ZoneInfo:
    return ZoneInfo(cfg()["timezone"])


def _at(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(h, m), tz())


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def closed_days() -> set[date]:
    return {date.fromisoformat(str(x["date"])) for x in cfg().get("closed_days", [])}


def session_open_on(d: date) -> bool:
    """Is the session that ends at 20:00 ET on day d open? (Mon-Fri, not a closed day.)"""
    return d.weekday() < 5 and d not in closed_days()


def windows_between(first: date, last: date) -> list[Window]:
    """Every window whose end falls on or before `last` 23:59 ET and whose start is on or after `first`."""
    w = cfg()["windows"]
    settle = timedelta(minutes=int(w["closed_settle_minutes"]))
    cut_before = timedelta(minutes=int(w["closed_cutoff_minutes_before_reopen"]))
    out: list[Window] = []
    d = first - timedelta(days=7)
    prev_end: datetime | None = None
    while d <= last + timedelta(days=7):
        if session_open_on(d):
            start = _at(d - timedelta(days=1), "20:00")
            if prev_end is not None and prev_end > start:
                start = prev_end
            end = _at(d, "20:00")
            out.append(Window(window_id(KIND_DAILY, d), KIND_DAILY,
                              f"daily {d.isoformat()} ({d.strftime('%a')})", _ms(start), _ms(start), _ms(end)))
            prev_end = end
            d += timedelta(days=1)
            continue
        # a closed span starts at 20:00 on the eve of d (the last open session's end) and lasts while
        # sessions stay closed; it reopens at 20:00 on the eve of the next open session
        span_start_day = d - timedelta(days=1)
        e = d
        while not session_open_on(e):
            e += timedelta(days=1)
        start = _at(span_start_day, "20:00")
        reopen = _at(e - timedelta(days=1), "20:00")
        end = reopen + settle
        out.append(Window(
            window_id(KIND_WEEKEND, span_start_day), KIND_WEEKEND,
            f"closed {span_start_day.isoformat()} ({span_start_day.strftime('%a')}) -> "
            f"{(e - timedelta(days=1)).isoformat()} ({(e - timedelta(days=1)).strftime('%a')})",
            _ms(start), _ms(reopen - cut_before), _ms(end), _ms(reopen)))
        prev_end = end
        d = e
    lo = _ms(_at(first, "00:00"))
    hi = _ms(_at(last, "23:59"))
    seen, res = set(), []
    for x in out:
        if x.start_ms >= lo and x.end_ms <= hi and x.id not in seen:
            seen.add(x.id)
            res.append(x)
    return sorted(res, key=lambda x: x.start_ms)


def window_by_id(wid: int) -> Window | None:
    from .commits import parse_window_id
    _, d = parse_window_id(wid)
    for x in windows_between(d - timedelta(days=3), d + timedelta(days=6)):
        if x.id == wid:
            return x
    return None


def et(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz()).strftime("%Y-%m-%d %a %H:%M %Z")
