"""The raw store: append-only JSONL of chain logs, the replay input of every published number.

Layout: data/raw/<stream>/<YYYY-MM-DD>.jsonl (UTC day of the block), one log per line with sorted keys:
  {"address", "block", "data", "log_index", "topics", "ts_ms", "tx"}
plus data/raw/<stream>/cursor.json {"to_block": n, "spec": {...}} recording how far the stream has been
read and with which filter. Lines within a day file are in (block, log_index) order; a re-read of a range
already covered never appends a duplicate (dedupe on (block, log_index, address)).

Everything is written with LF line endings and no trailing spaces, so file hashes are stable across OSes.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from . import config


COMPACT = {"swaps", "swaps_v4"}   # high-volume streams: gzip day files, data words as signed decimals


def raw_dir(stream: str) -> Path:
    return config.data_dir() / "raw" / stream


def _ext(stream: str) -> str:
    return ".jsonl.gz" if stream in COMPACT else ".jsonl"


def _pack(row: dict) -> dict:
    """Lossless: data hex -> list of 32-byte words as signed decimal strings (int256 two's complement)."""
    if "data" not in row:
        return row
    raw = row["data"][2:]
    ws = []
    for i in range(0, len(raw), 64):
        v = int(raw[i: i + 64], 16)
        ws.append(str(v - (1 << 256) if v >> 255 else v))
    out = {k: v for k, v in row.items() if k != "data"}
    out["w"] = ws
    out["dl"] = len(raw) // 2   # data length in bytes (a trailing partial word is not expected, kept exact)
    return out


def _unpack(row: dict) -> dict:
    if "w" not in row:
        return row
    h = "".join(f"{int(x) % (1 << 256):064x}" for x in row["w"])[: 2 * row.get("dl", 32 * len(row["w"]))]
    out = {k: v for k, v in row.items() if k not in ("w", "dl")}
    out["data"] = "0x" + h
    return out


def row_words(row: dict) -> list[int]:
    """The 32-byte data words of a row, unsigned, whether it is packed or not."""
    if "w" in row:
        return [int(x) % (1 << 256) for x in row["w"]]
    raw = row["data"][2:]
    return [int(raw[i: i + 64], 16) for i in range(0, len(raw), 64)]


def _read_lines(p: Path) -> list[str]:
    if p.suffix == ".gz":
        import gzip
        return gzip.decompress(p.read_bytes()).decode("utf-8").splitlines()
    return p.read_text(encoding="utf-8").splitlines()


# A fixed gzip header: no file name, mtime 0, "maximum compression", OS 255 (unknown). gzip.compress with
# mtime=0 lets zlib write the header, and zlib writes the OS it was built for (10 on Windows, 3 on Unix), so
# the same rows gave different file bytes on different machines (found 2026-11-10 comparing a CI re-read).
_GZ_HEADER = bytes([0x1F, 0x8B, 0x08, 0x00, 0, 0, 0, 0, 0x02, 0xFF])


def gzip_bytes(data: bytes) -> bytes:
    import struct
    import zlib
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return _GZ_HEADER + c.compress(data) + c.flush() + struct.pack("<II", zlib.crc32(data), len(data) & 0xFFFFFFFF)


def content(p: Path) -> bytes:
    """The bytes a file stands for: the uncompressed JSONL of a .gz day file, the file itself otherwise.
    Export manifests hash this, so a re-read matches on any machine whatever its zlib (METHODS section 2)."""
    b = p.read_bytes()
    if p.suffix == ".gz":
        import gzip
        return gzip.decompress(b)
    return b


def _write_lines(p: Path, lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    if p.suffix == ".gz":
        p.write_bytes(gzip_bytes(text.encode("utf-8")))
    else:
        p.write_text(text, encoding="utf-8", newline="\n")


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, UTC).strftime("%Y-%m-%d")


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def norm_log(log: dict, ts_ms: int) -> dict:
    return {
        "address": log["address"].lower(),
        "block": int(log["blockNumber"], 16) if isinstance(log["blockNumber"], str) else int(log["blockNumber"]),
        "data": log.get("data", "0x"),
        "log_index": int(log["logIndex"], 16) if isinstance(log["logIndex"], str) else int(log["logIndex"]),
        "topics": [t.lower() for t in log.get("topics", [])],
        "ts_ms": ts_ms,
        "tx": log.get("transactionHash", "").lower(),
    }


def _key(row: dict) -> tuple:
    return (row["block"], row["log_index"], row["address"])


def append(stream: str, rows: list[dict]) -> int:
    """Merge rows into their day files; returns how many were new."""
    if not rows:
        return 0
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[_day(r["ts_ms"])].append(r)
    d = raw_dir(stream)
    d.mkdir(parents=True, exist_ok=True)
    new = 0
    compact = stream in COMPACT
    for day, items in by_day.items():
        p = d / f"{day}{_ext(stream)}"
        existing = {}
        if p.exists():
            for line in _read_lines(p):
                if line:
                    row = json.loads(line)
                    existing[_key(row)] = row
        before = len(existing)
        for r in items:
            existing.setdefault(_key(r), _pack(r) if compact else r)
        new += len(existing) - before
        _write_lines(p, [dumps(existing[k]) for k in sorted(existing)])
    return new


def read(stream: str, from_ms: int | None = None, to_ms: int | None = None, packed: bool = False) -> Iterator[dict]:
    """Rows in order. packed=True leaves compact rows as stored (data words in `w`, see row_words)."""
    d = raw_dir(stream)
    if not d.exists():
        return
    for p in sorted(d.glob(f"*{_ext(stream)}")):
        for line in _read_lines(p):
            if not line:
                continue
            row = json.loads(line)
            if not packed:
                row = _unpack(row)
            if from_ms is not None and row["ts_ms"] < from_ms:
                continue
            if to_ms is not None and row["ts_ms"] > to_ms:
                continue
            yield row


def cursor(stream: str) -> dict | None:
    p = raw_dir(stream) / "cursor.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def set_cursor(stream: str, to_block: int, spec: dict) -> None:
    d = raw_dir(stream)
    d.mkdir(parents=True, exist_ok=True)
    (d / "cursor.json").write_text(dumps({"spec": spec, "to_block": to_block}) + "\n", encoding="utf-8",
                                   newline="\n")


def files(stream: str) -> list[Path]:
    d = raw_dir(stream)
    return sorted(d.glob(f"*{_ext(stream)}")) if d.exists() else []
