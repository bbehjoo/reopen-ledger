import json

from eth_utils import keccak

from callrec import attribution, config, housecommit, housedue, tx


def test_create_address_vectors():
    s = "0x6ac7ea33f8831ea9dcc53393aaa88b25a785dbf0"
    assert tx.create_address(s, 0).lower() == "0xcd234a471b72ba2f1ccf0a70fcaba648a5eecd8d"
    assert tx.create_address(s, 1).lower() == "0x343c43a37d37dff08ae8c4a11544c718abb4fcf8"


def test_committed_artifact_is_the_current_source():
    a = tx.artifact()
    src = (config.ROOT / a["source"]).read_bytes()
    assert a["source_keccak256"] == "0x" + keccak(src).hex().removeprefix("0x")
    out = config.ROOT / "contracts" / "out" / "CallLedger.sol" / "CallLedger.json"
    if out.exists():   # a local forge build must agree with the committed bytes
        j = json.loads(out.read_text(encoding="utf-8"))
        if j["metadata"]["sources"]["src/CallLedger.sol"]["keccak256"] == a["source_keccak256"]:
            assert j["bytecode"]["object"] == a["bytecode"]
            assert j["deployedBytecode"]["object"] == a["deployed_bytecode"]


def test_project_code_is_in_every_house_suffix():
    code = attribution.project_code()
    assert code and code.startswith("bc_")
    assert attribution.from_calldata("0xabcd" + housecommit.suffix_for({}).hex()) == [code]
    assert attribution.from_calldata("0x" + housecommit.suffix_for({}, ["bc_wallet"]).hex()) == [code, "bc_wallet"]


def test_nothing_is_sent_before_the_ledger_is_recorded(monkeypatch):
    monkeypatch.setattr(tx, "ledgers", lambda network=None: {})
    assert housedue.run_due("base", now_ms=1_795_000_000_000) == [{"status": "not_deployed", "network": "base"}]
    assert not housecommit.deployed("base")


def test_existing_record_search_starts_an_hour_before_the_house_slot():
    from datetime import date

    from callrec.calendar import windows_between
    from callrec.chain import schedule
    n = tx.Net("base", 8453, None)
    ws = {w.id: w for w in windows_between(date(2026, 11, 16), date(2026, 11, 22))}
    daily, closed = ws[220261117], ws[120261120]
    sb = lambda ms: schedule().block_at_or_before_ms(ms)  # noqa: E731
    assert housecommit.since_block_for(n, daily, {}) == sb(daily.cutoff_ms - 3 * 3_600_000)
    assert housecommit.since_block_for(n, closed, {}) == sb(closed.start_ms - 3_600_000)
    assert housecommit.since_block_for(n, closed, {"block": 10**9}) == 10**9   # never before the deploy
    assert housecommit.since_block_for(n, None, {}, since_ms=closed.start_ms) == sb(closed.start_ms - 3_600_000)
