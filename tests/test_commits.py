from datetime import date

import pytest
from eth_abi import decode as abi_decode

from callrec import attribution, commits
from callrec.commits import Call, CoverageEntry

NVDA = "0xb20000000000000000000078ee7ce2fe4908108c"
TSLA = "0xb2000000000000000000001e800a7f5189430cd0"


def test_window_ids_round_trip():
    w = commits.window_id(commits.KIND_WEEKEND, date(2026, 11, 13))
    assert w == 120261113
    assert commits.parse_window_id(w) == (1, date(2026, 11, 13))
    assert w < 2 ** 32


def test_calls_round_trip_sorted_and_none():
    calls = [Call(TSLA, 6200, -35), Call(NVDA, 5000, None)]
    data = commits.encode_calls(calls)
    assert len(data) == 52
    out = commits.decode_calls(data)
    assert out == sorted(calls, key=lambda c: c.token)
    assert {c.token for c in out} == {NVDA, TSLA}


def test_calls_reject_out_of_range():
    with pytest.raises(ValueError):
        commits.encode_calls([Call(NVDA, 10_001, None)])


def test_coverage_round_trip_with_unmeasured():
    e = CoverageEntry(NVDA, (120_000, 250_000, 400_000), (0, 1_500, None), (0, 0, None))
    data = commits.encode_coverage(54_000_000, [e])
    blk, out = commits.decode_coverage(data)
    assert blk == 54_000_000 and out == [e]


def test_anchor_round_trip():
    h = bytes(range(32))
    data = commits.encode_anchor(h, date(2026, 11, 9))
    assert commits.decode_anchor(data) == (h, 20261109)


def test_commit_calldata_is_valid_abi_and_carries_the_suffix():
    data = commits.encode_calls([Call(NVDA, 5000, 0)])
    suffix = attribution.to_suffix(["bc_test1"])
    cd = commits.commit_calldata(120261113, 1, data, suffix)
    raw = bytes.fromhex(cd[2:])
    from eth_utils import keccak
    assert raw[:4] == keccak(text="commit(uint32,uint16,bytes)")[:4]
    w, s, d = abi_decode(["uint32", "uint16", "bytes"], raw[4:])
    assert (w, s, d) == (120261113, 1, data)
    assert attribution.from_calldata(raw) == ["bc_test1"]


def test_suffix_matches_ox_example():
    # ox/erc8021 Attribution.ts doc example: codes ["baseapp", "morpho"] (schema 0)
    assert attribution.to_suffix(["baseapp", "morpho"]).hex() == \
        "626173656170702c6d6f7270686f0e0080218021802180218021802180218021"
    assert attribution.from_calldata("0x00" + attribution.to_suffix(["baseapp", "morpho"]).hex()) == \
        ["baseapp", "morpho"]
    assert attribution.from_calldata("0x1234") is None


def test_decode_committed_event_row():
    from eth_abi import encode
    payload = commits.encode_calls([Call(NVDA, 7000, 12)])
    row = {
        "topics": [commits.COMMITTED_TOPIC, "0x" + "00" * 12 + "ab" * 20,
                   "0x" + f"{120261113:064x}", "0x" + f"{1:064x}"],
        "data": "0x" + encode(["bytes"], [payload]).hex(),
        "block": 1, "ts_ms": 2, "tx": "0xt", "log_index": 0,
    }
    r = commits.decode_committed(row)
    assert r.committer == "0x" + "ab" * 20 and r.window == 120261113 and r.schema == 1 and r.data == payload
