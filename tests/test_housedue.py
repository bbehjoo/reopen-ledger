from datetime import datetime
from zoneinfo import ZoneInfo

from callrec.housedue import due_slots

ET = ZoneInfo("America/New_York")


def ms(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


def roles(now):
    return sorted((w.id, role) for w, role, _ in due_slots(now))


def test_friday_evening_after_close_opens_closed_window_and_coverage():
    got = roles(ms(2026, 11, 13, 20, 5))
    assert (120261113, "coverage") in got and (120261113, "null") in got and (120261113, "persistence") in got
    assert (120261113, "dex_implied") not in got


def test_sunday_afternoon_dex_implied_slot():
    got = roles(ms(2026, 11, 15, 16, 30))
    assert (120261113, "dex_implied") in got and (120261113, "coverage") not in got


def test_past_cutoff_nothing_for_that_window():
    got = roles(ms(2026, 11, 15, 18, 1))
    assert not any(w == 120261113 for w, _ in got)


def test_daily_window_hour_before_cutoff():
    # daily window for Tue Nov 17 starts (and is cut off) Mon Nov 16 20:00 ET
    got = roles(ms(2026, 11, 16, 19, 15))
    assert {(220261117, "null"), (220261117, "persistence"), (220261117, "dex_implied")} <= set(got)
    assert not any(w == 220261117 for w, _ in roles(ms(2026, 11, 16, 18, 30)))


def test_thanksgiving_span_has_its_own_slots():
    got = roles(ms(2026, 11, 25, 20, 10))
    assert (120261125, "coverage") in got
