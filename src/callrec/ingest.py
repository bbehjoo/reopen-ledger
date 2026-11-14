"""Resumable log ingest into the raw store.

A stream is (name, addresses, topics). Its cursor records the last block read and the addresses it covered.
Addresses added to a stream later are backfilled from the start block up to the cursor first, so a stream's
coverage is always "every listed address, from start_block to cursor.to_block".
"""

from __future__ import annotations

import logging

from . import chain as chainmod
from . import config, store

log = logging.getLogger(__name__)
CHUNK = 10_000


def head_target(rpc) -> int:
    sched = chainmod.schedule()
    head = rpc.block_number()
    guard_ms = int(config.chain().get("reorg_guard_seconds", 60)) * 1000
    return sched.block_at_or_before_ms(sched.ts_ms(head) - guard_ms)


def _read(rpc, stream: str, addresses: list[str] | None, topics: list, a: int, b: int, spec: dict | None,
          progress=None, address_prefix: str | None = None) -> int:
    sched = chainmod.schedule()
    new = 0
    for lo in range(a, b + 1, CHUNK):
        hi = min(lo + CHUNK - 1, b)
        logs = rpc.get_logs(addresses, topics, lo, hi)
        if address_prefix:
            logs = [x for x in logs if x["address"].lower().startswith(address_prefix)]
        rows = [store.norm_log(x, sched.ts_ms(int(x["blockNumber"], 16))) for x in logs if not x.get("removed")]
        new += store.append(stream, rows)
        if spec is not None:
            store.set_cursor(stream, hi, spec)
        if progress:
            progress(stream, lo, hi, b, len(rows))
    return new


def run_stream(rpc, stream: str, addresses: list[str], topics: list, start_block: int,
               to_block: int | None = None, progress=None) -> dict:
    addresses = sorted({a.lower() for a in addresses})
    to_block = to_block if to_block is not None else head_target(rpc)
    cur = store.cursor(stream)
    spec = {"addresses": addresses, "topics": topics, "start_block": start_block}
    new = 0
    if cur is None:
        frm = start_block
    else:
        old = set(cur["spec"].get("addresses", []))
        added = [a for a in addresses if a not in old]
        if cur["spec"].get("topics") != topics:
            raise RuntimeError(f"stream {stream}: topic filter changed; start a new stream name")
        if added:
            log.info("stream %s: backfilling %d new addresses to %d", stream, len(added), cur["to_block"])
            new += _read(rpc, stream, added, topics, start_block, cur["to_block"], None, progress)
            store.set_cursor(stream, cur["to_block"], spec)
        frm = cur["to_block"] + 1
    if frm <= to_block:
        new += _read(rpc, stream, addresses, topics, frm, to_block, spec, progress)
    return {"stream": stream, "new": new, "to_block": max(to_block, frm - 1)}


def parallel_backfill(urls: list[str], stream: str, addresses: list[str], topics: list, start_block: int,
                      to_block: int, workers: int = 4, progress=None) -> dict:
    """A fresh stream read in `workers` block segments at once, each on its own connection pool; rows are
    appended under a lock, and the cursor is set only when every segment has finished."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import json as _json
    import time as _time

    from .rpc import RpcError
    from .rpcpool import RpcPool
    if store.cursor(stream) is not None:
        raise RuntimeError(f"stream {stream} already has a cursor; use run_stream")
    addresses = sorted({a.lower() for a in addresses})
    sched = chainmod.schedule()
    lock = threading.Lock()
    d = store.raw_dir(stream)
    d.mkdir(parents=True, exist_ok=True)
    prog_path = d / "backfill-progress.json"
    spec = {"addresses": addresses, "topics": topics, "start_block": start_block}
    prog = _json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else None
    if prog and prog["spec"] == spec:
        to_block = prog["to_block"]          # a resumed backfill keeps its first target
    else:
        prog = {"spec": spec, "to_block": to_block, "done": []}
    seg = 100_000
    segments = [(a, min(a + seg - 1, to_block)) for a in range(start_block, to_block + 1, seg)]
    done_set = {tuple(x) for x in prog["done"]}
    todo = [s for s in segments if s not in done_set]
    state = {"rows": 0}

    def save_prog():
        prog_path.write_text(_json.dumps(prog, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    def work(ab):
        a, b = ab
        rpc = RpcPool(urls)
        buf: list[dict] = []          # one write per segment: a day file is rewritten once, not per chunk
        for lo in range(a, b + 1, CHUNK):
            hi = min(lo + CHUNK - 1, b)
            for attempt in range(6):
                try:
                    logs = rpc.get_logs(addresses, topics, lo, hi)
                    break
                except RpcError:
                    if attempt == 5:
                        raise
                    _time.sleep(5 * (attempt + 1))
            buf += [store.norm_log(x, sched.ts_ms(int(x["blockNumber"], 16))) for x in logs if not x.get("removed")]
        with lock:
            store.append(stream, buf)
            state["rows"] += len(buf)
            prog["done"].append([a, b])
            save_prog()
            if progress:
                progress(stream, a, b, to_block, state["rows"])

    save_prog()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    store.set_cursor(stream, to_block, spec)
    prog_path.unlink(missing_ok=True)
    return {"stream": stream, "rows": state["rows"], "to_block": to_block, "segments": len(segments),
            "resumed_skipped": len(segments) - len(todo)}


def run_topic_stream(rpc, stream: str, topics: list, start_block: int, address_prefix: str,
                     to_block: int | None = None, progress=None) -> dict:
    """A stream filtered by topics only (no address list), keeping logs whose emitter starts with
    `address_prefix` (B20 tokens share the 0xb2000000000000000000 prefix). Tokens added to the official
    list later are covered retroactively, since nothing was filtered by address at read time."""
    to_block = to_block if to_block is not None else head_target(rpc)
    cur = store.cursor(stream)
    spec = {"address_prefix": address_prefix, "topics": topics, "start_block": start_block}
    if cur is not None and cur["spec"] != spec:
        raise RuntimeError(f"stream {stream}: filter changed; start a new stream name")
    frm = start_block if cur is None else cur["to_block"] + 1
    new = 0
    if frm <= to_block:
        new = _read(rpc, stream, None, topics, frm, to_block, spec, progress, address_prefix)
    return {"stream": stream, "new": new, "to_block": max(to_block, frm - 1)}
