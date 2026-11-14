"""Block number <-> time on Base, from the segments in config/chain.yaml (exact on both sides of Denim).

Block n of a segment is at first_ts_ms + (n - first_block) * block_ms; the header's whole-second timestamp
is the floor of that. Nothing here reads the chain; `check_schedule` compares the schedule with headers.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from functools import cache

from . import config


@dataclass(frozen=True)
class Segment:
    first_block: int
    first_ts_ms: int
    block_ms: int

    def ts_ms(self, block: int) -> int:
        return self.first_ts_ms + (block - self.first_block) * self.block_ms


@dataclass(frozen=True)
class Schedule:
    segments: tuple[Segment, ...]

    def _i_block(self, block: int) -> int:
        return max(0, bisect.bisect_right([s.first_block for s in self.segments], block) - 1)

    def ts_ms(self, block: int) -> int:
        return self.segments[self._i_block(block)].ts_ms(block)

    def ts(self, block: int) -> int:
        return self.ts_ms(block) // 1000

    def block_at_or_before_ms(self, ts_ms: int) -> int:
        """The last block timed at or before `ts_ms`."""
        i = max(0, bisect.bisect_right([s.first_ts_ms for s in self.segments], ts_ms) - 1)
        s = self.segments[i]
        n = s.first_block + (ts_ms - s.first_ts_ms) // s.block_ms
        if i + 1 < len(self.segments):
            n = min(n, self.segments[i + 1].first_block - 1)
        return n

    def first_block_at_or_after(self, ts: int) -> int:
        """The first block whose time (ms) is at or after `ts` seconds."""
        b = self.block_at_or_before_ms(ts * 1000 - 1)
        return b + 1

    def to_manifest(self) -> list[dict]:
        return [{"first_block": s.first_block, "first_ts_ms": s.first_ts_ms, "block_ms": s.block_ms}
                for s in self.segments]


def schedule_from(segments: list[dict]) -> Schedule:
    return Schedule(tuple(Segment(int(s["first_block"]), int(s["first_ts_ms"]), int(s["block_ms"]))
                          for s in segments))


@cache
def schedule() -> Schedule:
    return schedule_from(config.chain()["block_time"])


def check_schedule(rpc, sched: Schedule, blocks: list[int]) -> list[dict]:
    """Compare header times with the schedule at `blocks`; returns one row per block (ok or not)."""
    out = []
    for n in blocks:
        b = rpc.get_block(n)
        ts = int(b["timestamp"], 16)
        ms = int(b["timestampMs"], 16) if b.get("timestampMs") else None
        want = sched.ts_ms(n)
        ok = (ts == want // 1000) and (ms is None or ms == want)
        out.append({"block": n, "timestamp": ts, "timestampMs": ms, "schedule_ms": want, "ok": ok})
    return out
