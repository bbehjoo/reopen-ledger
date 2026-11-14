"""End to end on synthetic raw data: export, then replay, gives identical files and a valid signature."""

import json
from datetime import UTC, datetime, timedelta

from callrec import config, feeds, signing, store

TOPIC = config.chain()["chainlink_events"]["AnswerUpdated"]


def _feed_rows(agg: str, start: datetime, days: int, price: float):
    rows, block = [], 50_400_000
    t = start
    end = start + timedelta(days=days)
    i = 0
    while t < end:
        if t.weekday() < 5:
            i += 1
            p = price * (1 + 0.002 * ((i % 7) - 3))
            ts_ms = int(t.timestamp() * 1000)
            rows.append({"address": agg, "block": block + i, "data": "0x" + f"{int(t.timestamp()):064x}",
                         "log_index": 0, "topics": [TOPIC, "0x" + f"{int(p * 1e8):064x}", "0x" + f"{i:064x}"],
                         "ts_ms": ts_ms, "tx": f"0x{i:064x}"})
        t += timedelta(hours=1)
    return rows


def test_export_then_replay_is_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLREC_DATA", str(tmp_path))
    monkeypatch.setenv(signing.ENV_VAR, signing.new_key_b64())
    fs = [f for f in feeds.load() if f["kind"] == "24/5" and f.get("token")][:2]
    for k, f in enumerate(fs):
        agg = f["chain"]["phase_aggregators"][-1]["aggregator"]
        store.append("feeds", _feed_rows(agg, datetime(2026, 8, 24, tzinfo=UTC), 9, 100.0 + 50 * k))
    from callrec import export
    as_of = int(datetime(2026, 9, 2, 12, tzinfo=UTC).timestamp() * 1000)
    res = export.export_run(as_of, tmp_path / "exp")
    assert res["signed"] and res["files"] > 10
    rep = export.replay(tmp_path / "exp")
    assert rep["differences"] == [] and rep["identical"]
    m = json.loads((tmp_path / "exp" / "manifest.json").read_text(encoding="utf-8"))
    sk = signing.key_from_env()
    assert signing.verify_document(m, sk.public_key())
    tape = (tmp_path / "exp" / "tape.csv").read_text(encoding="utf-8")
    assert tape.count("\n") > 1


def test_as_of_never_passes_the_data(tmp_path, monkeypatch):
    import pytest

    from callrec import export, store
    from callrec.chain import schedule
    monkeypatch.setenv("CALLREC_DATA", str(tmp_path))
    t0 = 1_794_200_000_000                         # a time after Denim
    blk = schedule().block_at_or_before_ms
    store.set_cursor("swaps", blk(t0 - 95_000), {})   # read to 95 s before
    store.set_cursor("feeds", blk(t0 + 60_000), {})   # read past it
    eff, cov = export.effective_as_of(t0)
    assert eff <= cov["swaps"] and eff % 60_000 == 0 and t0 - eff < 3 * 60_000
    store.set_cursor("swaps", blk(t0 - 3 * 3_600_000), {})
    with pytest.raises(export.ExportError, match="swaps"):
        export.effective_as_of(t0)
    assert export.effective_as_of(t0, max_lag_ms=4 * 3_600_000)[0] <= t0 - 3 * 3_600_000
