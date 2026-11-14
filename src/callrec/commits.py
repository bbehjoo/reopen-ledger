"""What a CallLedger record means: window ids and the three data schemas (METHODS.md sections 3 and 4).

Window id = kind * 100_000_000 + yyyymmdd, the date in US Eastern time:
  kind 1  weekend window, dated by its Friday
  kind 2  daily window, dated by its trading day
  kind 3  a calendar day (the daily anchor)

Schema 1, probability calls. Concatenated 26-byte entries, one per token:
  token (20 bytes) | p_up_bps uint16 (0..10000) | ret_bps int32 (expected log return in basis points;
  0x80000000 = none given)
  p_up_bps is the probability, in basis points, that the reference value at the window's end is above its
  value at the window's start.
Schema 2, coverage call. snapshot_block uint64, then 74-byte entries, one per token:
  token (20 bytes) | for each shock 5%, 10%, 20%: depth_usd uint48 | liquidation_flow_usd uint48 |
  underwater_debt_usd uint48   (whole dollars; 0xFFFFFFFFFFFF = not measured)
Schema 3, daily anchor. sha256 of the day's export manifest (32 bytes) | export date yyyymmdd uint32.

The scorer counts the first record per (committer, window, schema, token); later ones are kept and shown,
never scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from eth_utils import keccak

from .abi import enc_uint

COMMITTED_TOPIC = "0x" + keccak(text="Committed(address,uint32,uint16,bytes)").hex()
COMMIT_SIG = "commit(uint32,uint16,bytes)"
KIND_WEEKEND, KIND_DAILY, KIND_DAY = 1, 2, 3
SCHEMA_CALLS, SCHEMA_COVERAGE, SCHEMA_ANCHOR = 1, 2, 3
SHOCKS_BPS = (500, 1000, 2000)
RET_NONE = -(2 ** 31)
USD_NONE = 2 ** 48 - 1


def window_id(kind: int, d: date) -> int:
    return kind * 100_000_000 + d.year * 10_000 + d.month * 100 + d.day


def parse_window_id(w: int) -> tuple[int, date]:
    kind, rest = divmod(w, 100_000_000)
    return kind, date(rest // 10_000, rest // 100 % 100, rest % 100)


@dataclass(frozen=True)
class Call:
    token: str          # lowercase 0x address
    p_up_bps: int
    ret_bps: int | None


def encode_calls(calls: list[Call]) -> bytes:
    out = bytearray()
    for c in sorted(calls, key=lambda c: c.token):
        if not 0 <= c.p_up_bps <= 10_000:
            raise ValueError(f"p_up_bps out of range: {c.p_up_bps}")
        r = RET_NONE if c.ret_bps is None else c.ret_bps
        if not RET_NONE < r < 2 ** 31 and c.ret_bps is not None:
            raise ValueError("ret_bps out of range")
        out += bytes.fromhex(c.token.removeprefix("0x")) + c.p_up_bps.to_bytes(2, "big") \
            + r.to_bytes(4, "big", signed=True)
    return bytes(out)


def decode_calls(data: bytes) -> list[Call]:
    if len(data) % 26:
        raise ValueError(f"schema 1 data length {len(data)} is not a multiple of 26")
    out = []
    for i in range(0, len(data), 26):
        e = data[i: i + 26]
        r = int.from_bytes(e[22:26], "big", signed=True)
        out.append(Call("0x" + e[:20].hex(), int.from_bytes(e[20:22], "big"), None if r == RET_NONE else r))
    return out


@dataclass(frozen=True)
class CoverageEntry:
    token: str
    depth_usd: tuple[int | None, int | None, int | None]
    liquidation_flow_usd: tuple[int | None, int | None, int | None]
    underwater_debt_usd: tuple[int | None, int | None, int | None]


def _u48(v: int | None) -> bytes:
    v = USD_NONE if v is None else max(0, min(int(v), USD_NONE - 1))
    return v.to_bytes(6, "big")


def encode_coverage(snapshot_block: int, entries: list[CoverageEntry]) -> bytes:
    out = bytearray(snapshot_block.to_bytes(8, "big"))
    for e in sorted(entries, key=lambda e: e.token):
        out += bytes.fromhex(e.token.removeprefix("0x"))
        for i in range(3):
            out += _u48(e.depth_usd[i]) + _u48(e.liquidation_flow_usd[i]) + _u48(e.underwater_debt_usd[i])
    return bytes(out)


def decode_coverage(data: bytes) -> tuple[int, list[CoverageEntry]]:
    if len(data) < 8 or (len(data) - 8) % 74:
        raise ValueError("bad schema 2 length")
    block = int.from_bytes(data[:8], "big")
    out = []

    def u(b):
        v = int.from_bytes(b, "big")
        return None if v == USD_NONE else v

    for i in range(8, len(data), 74):
        e = data[i: i + 74]
        vals = [u(e[20 + 6 * k: 26 + 6 * k]) for k in range(9)]
        out.append(CoverageEntry("0x" + e[:20].hex(), tuple(vals[0::3]), tuple(vals[1::3]), tuple(vals[2::3])))
    return block, out


def encode_anchor(manifest_sha256: bytes, d: date) -> bytes:
    if len(manifest_sha256) != 32:
        raise ValueError("sha256 must be 32 bytes")
    return manifest_sha256 + (d.year * 10_000 + d.month * 100 + d.day).to_bytes(4, "big")


def decode_anchor(data: bytes) -> tuple[bytes, int]:
    if len(data) != 36:
        raise ValueError("bad schema 3 length")
    return data[:32], int.from_bytes(data[32:], "big")


def commit_calldata(window: int, schema: int, data: bytes, suffix: bytes = b"") -> str:
    """ABI-encoded commit(uint32,uint16,bytes) plus an optional attribution suffix."""
    sel = "0x" + keccak(text=COMMIT_SIG).hex()[:8]
    n = len(data)
    padded = data + b"\x00" * ((32 - n % 32) % 32)
    body = enc_uint(window) + enc_uint(schema) + enc_uint(96) + enc_uint(n) + padded.hex()
    return sel + body + suffix.hex()


@dataclass(frozen=True)
class Record:
    committer: str
    window: int
    schema: int
    data: bytes
    block: int
    ts_ms: int
    tx: str
    log_index: int


def decode_committed(row: dict) -> Record:
    t = row["topics"]
    raw = bytes.fromhex(row["data"][2:])
    off = int.from_bytes(raw[:32], "big")
    n = int.from_bytes(raw[off: off + 32], "big")
    return Record(
        committer="0x" + t[1][-40:],
        window=int(t[2], 16),
        schema=int(t[3], 16),
        data=raw[off + 32: off + 32 + n],
        block=row["block"],
        ts_ms=row["ts_ms"],
        tx=row["tx"],
        log_index=row["log_index"],
    )
