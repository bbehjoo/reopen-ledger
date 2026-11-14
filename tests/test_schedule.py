"""The house job's cron lines give every house record slot at least three firings (GitHub may delay or skip a
scheduled run), from the first slot after the cron change through the last EST day before DST."""

from datetime import UTC, date, datetime, timedelta

import yaml

from callrec import config
from callrec.housedue import due_slots

FIRST, LAST = date(2026, 11, 10), date(2027, 3, 13)   # EST throughout; DST starts 2027-03-14


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if part == "*":
            out |= set(range(lo, hi + 1))
        elif "-" in part:
            a, b = part.split("-")
            out |= set(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def _firings(crons: list[str]) -> list[int]:
    out = set()
    d = FIRST
    while d <= LAST + timedelta(days=1):
        for c in crons:
            mi, hh, dom, mon, dow = c.split()
            dow_ok = (d.isoweekday() % 7) in {x % 7 for x in _field(dow, 0, 7)}
            dom_ok = d.day in _field(dom, 1, 31)
            day_ok = (dom_ok and dow_ok) if "*" in (dom, dow) else (dom_ok or dow_ok)
            if d.month in _field(mon, 1, 12) and day_ok:
                for h in _field(hh, 0, 23):
                    for m in _field(mi, 0, 59):
                        out.add(int(datetime(d.year, d.month, d.day, h, m, tzinfo=UTC).timestamp() * 1000))
        d += timedelta(days=1)
    return sorted(out)


def _house_crons() -> list[str]:
    doc = yaml.safe_load((config.ROOT / ".github" / "workflows" / "house.yml").read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True))   # YAML 1.1 reads the key `on` as true
    return [s["cron"] for s in on["schedule"]]


def _all_slots() -> set[tuple[int, str]]:
    """Every (window, role) slot that opens in the range, found by sampling every 5 minutes."""
    every: set[tuple[int, str]] = set()
    t = int(datetime(FIRST.year, FIRST.month, FIRST.day, 6, tzinfo=UTC).timestamp() * 1000)
    end = int(datetime(LAST.year, LAST.month, LAST.day, 23, 59, tzinfo=UTC).timestamp() * 1000)
    while t < end:
        every |= {(w.id, role) for w, role, _ in due_slots(t)}
        t += 300_000
    return every


def _hits(fire: list[int]) -> dict[tuple[int, str], int]:
    hit: dict[tuple[int, str], int] = {}
    for f in fire:
        for w, role, _ in due_slots(f):
            hit[(w.id, role)] = hit.get((w.id, role), 0) + 1
    return hit


def _tick_crons() -> list[str]:
    doc = yaml.safe_load((config.ROOT / "config" / "house_ticks.yaml").read_text(encoding="utf-8"))
    return [t["cron"] for t in doc["ticks"]]


def test_punctual_ticks_give_every_house_slot_two_firings():
    hit = _hits(_firings(_tick_crons()))
    short = {k: hit.get(k, 0) for k in _all_slots() if hit.get(k, 0) < 2}
    assert not short, f"slots with fewer than 2 ticks: {sorted(short.items())[:10]}"


def test_late_github_cron_still_covers_null_and_persistence():
    """GitHub ran scheduled jobs 6 to 8 hours late; its cron alone must still reach every null and
    persistence slot when every run is 0, 4 or 8 hours late."""
    base = _firings(_house_crons())
    slots = {k for k in _all_slots() if k[1] in ("null", "persistence")}
    for delay_h in (0, 4, 8):
        hit = _hits([f + delay_h * 3_600_000 for f in base])
        missed = sorted(k for k in slots if not hit.get(k))
        assert not missed, f"{delay_h} h late: missed {missed[:10]}"


def test_tick_crons_respect_the_routine_minimum_interval():
    for c in _tick_crons():
        mi, hh = c.split()[:2]
        assert len(_field(mi, 0, 59)) == 1, f"{c}: a routine fires at most once an hour"


def test_cron_parser_reads_ranges_and_lists():
    assert _field("5,25,45", 0, 59) == {5, 25, 45}
    assert _field("2-5", 0, 7) == {2, 3, 4, 5}
    assert len(_field("*", 0, 23)) == 24
