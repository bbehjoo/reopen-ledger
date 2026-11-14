import hashlib

from callrec import store


def row(block, li, data, ts=1_793_000_000_000):
    return {"address": "0xpool", "block": block, "data": data, "log_index": li,
            "topics": ["0x" + "11" * 32, "0x" + "00" * 12 + "22" * 20], "ts_ms": ts, "tx": "0xt"}


def test_compact_stream_round_trips_losslessly_and_deterministically(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLREC_DATA", str(tmp_path))
    neg = "0x" + "ff" * 31 + "38" + "00" * 31 + "05" + "00" * 12 + "ab" * 20
    rows = [row(10, 1, neg), row(10, 0, "0x" + "00" * 31 + "01"), row(11, 0, "0x")]
    assert store.append("swaps", rows) == 3
    assert store.append("swaps", rows) == 0          # dedupe
    back = list(store.read("swaps"))
    assert [r["data"] for r in back] == ["0x" + "00" * 31 + "01", neg, "0x"]
    f = store.files("swaps")[0]
    h1 = hashlib.sha256(f.read_bytes()).hexdigest()
    store.append("swaps", rows)
    assert hashlib.sha256(f.read_bytes()).hexdigest() == h1   # same bytes on rewrite (gzip mtime 0)


def test_plain_stream_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLREC_DATA", str(tmp_path))
    store.append("feeds", [row(1, 0, "0x" + "00" * 32)])
    assert store.files("feeds")[0].suffix == ".jsonl"
    assert next(store.read("feeds"))["data"] == "0x" + "00" * 32


def test_gzip_bytes_are_machine_independent_and_content_hash_ignores_the_header(tmp_path):
    import gzip
    import hashlib

    from callrec import store
    data = b'{"a":1}\n{"b":2}\n'
    g = store.gzip_bytes(data)
    assert g[:10] == bytes([0x1F, 0x8B, 8, 0, 0, 0, 0, 0, 2, 0xFF]) and gzip.decompress(g) == data
    win = bytearray(g)
    win[9] = 10                     # the header zlib writes on Windows
    a, b = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    a.write_bytes(g)
    b.write_bytes(bytes(win))
    assert store.content(a) == store.content(b) == data
    assert hashlib.sha256(store.content(a)).hexdigest() == hashlib.sha256(data).hexdigest()
