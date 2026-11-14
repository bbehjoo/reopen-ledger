"""callrec command line. Every command that writes to the chain says so in its help, and is limited to
house commits and the daily anchor to the CallLedger contract."""

from __future__ import annotations

import json
import logging
import sys

import typer
from dotenv import load_dotenv

from . import config

app = typer.Typer(no_args_is_help=True, add_completion=False)
registry_app = typer.Typer(no_args_is_help=True)
feeds_app = typer.Typer(no_args_is_help=True)
ingest_app = typer.Typer(no_args_is_help=True)
app.add_typer(registry_app, name="registry", help="The official token registry (config/tokens.json).")
app.add_typer(feeds_app, name="feeds", help="Chainlink reference feeds (config/feeds.yaml).")
app.add_typer(ingest_app, name="ingest", help="Read chain logs into data/raw (read-only).")

load_dotenv(config.ROOT / ".env", override=False)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    stream=sys.stderr)
logging.getLogger("httpx").setLevel(logging.WARNING)

B20_PREFIX = "0xb2000000000000000000"


def rpc_for(role: str):
    from .rpcpool import RpcPool
    return RpcPool(config.rpc_urls(role))


def _progress(stream, lo, hi, end, n):
    if (hi // 10_000) % 20 == 0 or hi >= end:
        typer.echo(f"{stream}: {hi}/{end} (+{n})", err=True)


@app.command("chain-check")
def chain_check():
    """Compare the block-time schedule with block headers (read-only)."""
    from .chain import check_schedule, schedule
    r = rpc_for("state")
    head = r.block_number()
    rows = check_schedule(r, schedule(), [53556126, 53556127, 53556128, head - 1000, head])
    typer.echo(json.dumps(rows, indent=1))
    if not all(x["ok"] for x in rows):
        raise typer.Exit(5)


@registry_app.command("build")
def registry_build():
    """Fetch the official list and check every token on chain (read-only)."""
    from . import registry
    doc = registry.build_registry(rpc_for("state"))
    registry.write(doc)
    bad = [t["symbol"] for t in doc["tokens"] if not t["chain_matches_api"]]
    typer.echo(f"{doc['count']} tokens; chain differs from API for: {bad or 'none'}")


@feeds_app.command("build")
def feeds_build():
    """Discover the Coinbase equity feeds and read their phase aggregators (read-only)."""
    from . import feeds, registry
    doc = feeds.build_feeds(rpc_for("state"), registry.by_symbol())
    feeds.write(doc)
    for f in doc["feeds"]:
        typer.echo(f"{f['name']:<22} {f['kind']:<5} token={f['token_symbol']} phases={f['chain']['phase_id']}")


@ingest_app.command("feeds")
def ingest_feeds(to_block: int = typer.Option(None, help="last block (default: head minus guard)")):
    """Every AnswerUpdated of every phase aggregator since the backfill start."""
    from . import feeds, ingest
    fs = feeds.load()
    topic = config.chain()["chainlink_events"]["AnswerUpdated"]
    res = ingest.run_stream(rpc_for("logs"), feeds.STREAM, feeds.aggregator_addresses(fs), [[topic]],
                            config.chain()["backfill_start_block"], to_block, _progress)
    typer.echo(json.dumps(res))


@ingest_app.command("b20")
def ingest_b20(to_block: int = typer.Option(None)):
    """Multiplier, announcement, pause, policy and metadata events of every official token."""
    # publicnode refuses topic-only filters ("Please specify an address"), so the stream lists the measured
    # tokens (those with a 24/5 feed): the void rules need their events, nothing else does
    from . import ingest
    from .pools import _measured_tokens
    topics = [sorted(config.chain()["b20_events"].values())]
    res = ingest.run_stream(rpc_for("logs"), "b20", sorted(_measured_tokens()), topics,
                            config.chain()["backfill_start_block"], to_block, _progress)
    typer.echo(json.dumps(res))


@app.command("export")
def export_cmd(as_of: str = typer.Option("", help="UTC time YYYY-MM-DDTHH:MM (default: now minus 10 minutes)"),
               out: str = typer.Option("", help="output directory (default data/exports/<date>)"),
               max_lag_hours: float = typer.Option(2.0, help="fail when a stream is read less far than this "
                                                              "before as_of")):
    """Build every published file from data/raw and config into a signed export (no network). The export is
    as of the earliest time every stream has been read to, never later than requested."""
    from datetime import UTC, datetime

    from . import export
    if as_of:
        ms = int(datetime.strptime(as_of, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC).timestamp() * 1000)
    else:
        ms = int((datetime.now(UTC).timestamp() - 600) * 1000)
    try:
        res = export.export_run(ms, out or None, max_lag_ms=int(max_lag_hours * 3_600_000))
    except export.ExportError as e:
        typer.echo(f"export refused: {e}", err=True)
        raise typer.Exit(7)
    typer.echo(json.dumps(res, indent=1))


@app.command("inputs")
def inputs_cmd(prefix: str = typer.Option("", help="only inputs whose path starts with this")):
    """Print the SHA-256 of every input, as an export manifest records it (no network)."""
    from . import export
    typer.echo(json.dumps({k: v for k, v in export.input_hashes().items() if k.startswith(prefix)},
                          indent=0, sort_keys=True))


@app.command("replay")
def replay_cmd(export_dir: str = typer.Argument(...)):
    """Rebuild an export from the raw inputs and compare every output file with its manifest."""
    from . import export
    res = export.replay(export_dir)
    typer.echo(json.dumps(res, indent=1))
    if not res["identical"]:
        raise typer.Exit(1)


@app.command("site")
def site_cmd(export_dir: str = typer.Argument(...), out: str = typer.Option("site/build")):
    """Render the static site from an export directory (no network)."""
    from . import site
    pages = site.build_site(export_dir, config.ROOT / out)
    typer.echo(f"{len(pages)} pages in {out}")


ledger_app = typer.Typer(no_args_is_help=True)
house_app = typer.Typer(no_args_is_help=True)
app.add_typer(ledger_app, name="ledger", help="Deploy and inspect the CallLedger contract (writes to chain).")
app.add_typer(house_app, name="house", help="House wallets and house commits (writes to chain).")


@ledger_app.command("deploy")
def ledger_deploy(network: str = typer.Option(..., help="local, sepolia or base"),
                  builder_code: str = typer.Option("", help="default: config/attribution.yaml")):
    """WRITES TO CHAIN: deploy CallLedger from the anchor wallet's first transaction and record it in
    config/ledger.yaml (or record the one that transaction already created). Never deploys twice."""
    from . import attribution, house, tx
    if network in tx.ledgers(network):
        typer.echo(f"{network}: already recorded at {tx.ledger(network)['address']}; not deploying again")
        raise typer.Exit(1)
    acct = house.derive(house.mnemonic_from_env(), "anchor")
    entry = tx.deploy_or_recover(network, acct, builder_code or attribution.project_code())
    typer.echo(json.dumps(entry, indent=1))


def _house_log(network: str, rows: list[dict]) -> None:
    """Append every house transaction result (deploys, records with their attribution checks) to
    data/house-log/<YYYY-MM>.jsonl, which the jobs commit. Not a replay input."""
    from datetime import UTC, datetime
    keep = [r for r in rows if r.get("status") in ("sent", "deployed", "recovered")]
    if not keep or network == "local":
        return
    now = datetime.now(UTC)
    p = config.data_dir() / "house-log" / f"{now:%Y-%m}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        for r in keep:
            f.write(json.dumps({"logged_at": now.isoformat(timespec="seconds"), "network": network, **r},
                               sort_keys=True) + "\n")


BOOTSTRAP_MIN_ETH = {"base": 0.002, "sepolia": 0.002, "local": 0.002}
HOUSE_TARGET_ETH = {"base": 0.0004, "sepolia": 0.002, "local": 0.002}


def _github_output(**kv) -> None:
    import os
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


@house_app.command("bootstrap")
def house_bootstrap(network: str = typer.Option("base")):
    """WRITES TO CHAIN once: when the ledger is not recorded for `network` and the anchor wallet holds enough
    ETH, deploy it (RUNBOOK sections 1 and 3), top up the house wallets, and on Sepolia send one test record
    and repeat it (the second answer must be already_committed). Otherwise prints why it waited. Run by the
    house job on every firing, so funding the anchor wallet is the only manual step."""
    from . import attribution, house, housecommit, tx
    if network in tx.ledgers(network):
        typer.echo(f"{network}: ledger recorded at {tx.ledger(network)['address']}")
        _github_output(deployed_now="false")
        return
    n = tx.net(network)
    m = house.mnemonic_from_env()
    anchor = house.derive(m, "anchor")
    sent = int(n.rpc.call("eth_getTransactionCount", [anchor.address, "latest"]), 16)
    bal = tx.balance(n, anchor.address)
    need = int(BOOTSTRAP_MIN_ETH[network] * 1e18)
    if sent == 0 and bal < need:
        typer.echo(f"{network}: anchor {anchor.address} holds {bal / 1e18:.6f} ETH; waiting for "
                   f"{need / 1e18:.4f} ETH before deploying")
        _github_output(deployed_now="false")
        return
    entry = tx.deploy_or_recover(network, anchor, attribution.project_code())
    typer.echo(json.dumps(entry, indent=1))
    _house_log(network, [{**entry, "role": "anchor", "action": "deploy"}])
    _github_output(deployed_now="true")
    house_fund(network=network, target_eth=HOUSE_TARGET_ETH[network], dry_run=False)
    if network == "sepolia":
        from datetime import UTC, datetime, timedelta

        from .calendar import windows_between
        now = int(datetime.now(UTC).timestamp() * 1000)
        d = datetime.now(UTC).date()
        w = next(x for x in windows_between(d, d + timedelta(days=7)) if x.cutoff_ms > now + 600_000)
        for _ in range(2):
            house_commit_test(network=network, role="null", window=w.id, dry_run=False)


@house_app.command("pending")
def house_pending(network: str = typer.Option("base")):
    """Read-only gate for the house job: which due house records are not on the chain yet. Writes
    `pending=true|false` to $GITHUB_OUTPUT so the job skips the data steps when nothing is owed."""
    import time as _t

    from . import housecommit, housedue
    if not housecommit.deployed(network):
        typer.echo(f"{network}: no ledger recorded; nothing to send")
        _github_output(pending="false")
        return
    slots = housedue.due_slots(int(_t.time() * 1000))
    todo = housecommit.pending(network, slots) if slots else []
    typer.echo(json.dumps({"due": len(slots), "pending": todo}))
    _github_output(pending="true" if todo else "false")


@house_app.command("check-keys")
def house_check_keys():
    """Check that the secrets in this environment are the published ones: the house mnemonic derives the
    addresses in config/house.yaml, and EXPORT_SIGNING_KEY (when set) matches keys/export-key.json.
    Prints addresses and key ids only."""
    import yaml as _yaml

    from . import house, signing
    listed = {w["role"]: w["address"] for w in
              _yaml.safe_load((config.config_dir() / "house.yaml").read_text(encoding="utf-8"))["wallets"]}
    got = {w.role: w.address for w in house.addresses(house.mnemonic_from_env())}
    ok = got == listed
    typer.echo(f"house mnemonic: {'matches' if ok else 'DIFFERS FROM'} config/house.yaml (anchor {got['anchor']})")
    sk = signing.key_from_env()
    if sk is not None:
        pub = json.loads((config.ROOT / "keys" / "export-key.json").read_text(encoding="utf-8"))
        kid = signing.key_id(sk.public_key())
        same = kid == pub["key_id"]
        typer.echo(f"export signing key: {kid} {'matches' if same else 'DIFFERS FROM'} keys/export-key.json")
        ok = ok and same
    if not ok:
        raise typer.Exit(4)


@app.command("attribution")
def attribution_check(tx_hash: str = typer.Argument(...), network: str = typer.Option("base"),
                      official: bool = typer.Option(False, help="also ask Base's Builder Code checker")):
    """Read a transaction back from the chain and print the Builder Codes in its calldata (read-only).
    Exits 6 when this project's code is absent."""
    from . import attribution, housecommit, tx
    codes = housecommit.attribution_on_chain(tx.net(network), tx_hash)
    own = attribution.project_code()
    res = {"tx": tx_hash, "codes": codes, "project_code": own, "present": bool(codes and own in codes)}
    if official:
        res["official_check"] = housecommit.official_check(tx_hash)
    typer.echo(json.dumps(res))
    if not (codes and own in codes):
        raise typer.Exit(6)


@house_app.command("addresses")
def house_addresses():
    """Print the house wallet addresses (never the mnemonic)."""
    from . import house
    for w in house.addresses(house.mnemonic_from_env()):
        typer.echo(f"{w.index} {w.role:<12} {w.address}")


@house_app.command("balances")
def house_balances(network: str = typer.Option(...)):
    from . import house, tx
    n = tx.net(network)
    for w in house.addresses(house.mnemonic_from_env()):
        typer.echo(f"{w.role:<12} {w.address} {tx.balance(n, w.address) / 1e18:.6f} ETH")


@house_app.command("fund")
def house_fund(network: str = typer.Option(...), target_eth: float = typer.Option(0.0004),
               dry_run: bool = typer.Option(False)):
    """WRITES TO CHAIN: top up each house wallet below target_eth from the anchor wallet."""
    from . import house, tx
    n = tx.net(network)
    m = house.mnemonic_from_env()
    anchor = house.derive(m, "anchor")
    for w in house.addresses(m)[1:]:
        bal = tx.balance(n, w.address)
        want = int(target_eth * 1e18)
        if bal >= want // 2:
            typer.echo(f"{w.role:<12} has {bal / 1e18:.6f} ETH; no top-up")
            continue
        if dry_run:
            typer.echo(f"{w.role:<12} would receive {(want - bal) / 1e18:.6f} ETH")
            continue
        tx.send(n, anchor, w.address, "0x", value=want - bal, gas=21_000)


@house_app.command("commit-test")
def house_commit_test(network: str = typer.Option(...), role: str = typer.Option("null"),
                      window: int = typer.Option(...), dry_run: bool = typer.Option(False)):
    """WRITES TO CHAIN: a schema-1 record from a house wallet for a given window id, on the slate tokens
    with a feed (used for the Sepolia dry run and the first mainnet record)."""
    from . import feeds, housecommit
    slate = sorted({f["token"] for f in feeds.load() if f.get("token") and f["kind"] == "24/5"})
    from . import commits
    data = commits.encode_calls(housecommit.calls_for(role, slate))
    res = housecommit.commit(network, role, None, window, commits.SCHEMA_CALLS, data, dry_run=dry_run)
    typer.echo(json.dumps(res))
    _house_log(network, [res])


@ingest_app.command("ledger")
def ingest_ledger(network: str = typer.Option("base")):
    """Committed events of the CallLedger contract (stream `ledger`, mainnet only)."""
    from . import commits, ingest, tx
    if network not in tx.ledgers(network):
        typer.echo(f"{network}: no ledger recorded; nothing to read")
        return
    e = tx.ledger(network)
    res = ingest.run_stream(rpc_for("logs"), "ledger", [e["address"]], [[commits.COMMITTED_TOPIC]],
                            int(e["block"]), None, _progress)
    typer.echo(json.dumps(res))


@ingest_app.command("swaps")
def ingest_swaps(workers: int = typer.Option(4, help="parallel segments for a fresh stream")):
    """Swap (and classic-pool Sync) logs of every listed pool."""
    from . import ingest, pools, store
    specs = pools.stream_specs()
    if not specs:
        typer.echo("no pools listed in config/pools.yaml")
        raise typer.Exit(1)
    start = config.chain()["backfill_start_block"]
    for s in specs:
        if store.cursor(s["stream"]) is None:
            to = ingest.head_target(rpc_for("logs"))
            res = ingest.parallel_backfill(config.rpc_urls("logs"), s["stream"], s["addresses"], s["topics"], start,
                                           to, workers, _progress)
        else:
            res = ingest.run_stream(rpc_for("logs"), s["stream"], s["addresses"], s["topics"], start, None, _progress)
        typer.echo(json.dumps(res))


snapshot_app = typer.Typer(no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot", help="Pool depth and lending positions at one block (read-only).")


@ingest_app.command("lending")
def ingest_lending():
    """Morpho Blue and Aave V4 position events for the listed markets (who has a position)."""
    from . import coverage, ingest
    for s in coverage.stream_specs():
        res = ingest.run_stream(rpc_for("logs"), s["stream"], s["addresses"], s["topics"], s["start"], None, _progress)
        typer.echo(json.dumps(res))


@snapshot_app.command("all")
def snapshot_all():
    """Depth of every listed pool and every lending position, at one recent block."""
    from . import coverage
    typer.echo(json.dumps(coverage.snapshot_all(rpc_for("state")), indent=1))


@snapshot_app.command("offchain")
def snapshot_offchain():
    """Fetch the issuer list, token page, docs and feed directory; keep copies private, hashes on record."""
    from . import offchain
    for row in offchain.snapshot():
        typer.echo(f"{row['name']:<18} {row['status']} {row['bytes']:>9} {row['sha256'][:16]}")


@snapshot_app.command("if-coverage-due")
def snapshot_if_coverage_due():
    """Take a snapshot when a coverage record is due now, or within the hour after a reopen (house job)."""
    import time as _t
    from datetime import UTC, datetime, timedelta

    from . import coverage, housedue
    from .calendar import windows_between
    now = int(_t.time() * 1000)
    due = [s for s in housedue.due_slots(now) if s[1] == "coverage"]
    d = datetime.fromtimestamp(now / 1000, UTC).date()
    reopen = [w for w in windows_between(d - timedelta(days=4), d + timedelta(days=1))
              if w.kind == 1 and w.reopen_ms <= now < w.reopen_ms + 3_600_000]
    if not due and not reopen:
        typer.echo("no coverage slot or reopen hour open")
        return
    typer.echo(json.dumps(coverage.snapshot_all(rpc_for("state")), indent=1))


@app.command("drafts")
def drafts_cmd(export_dir: str = typer.Argument(...), date_tag: str = typer.Option(..., "--date")):
    """Render the launch post and the latest Weekend Report from an export into drafts/ (nothing is posted)."""
    from pathlib import Path

    from . import drafts
    d = config.ROOT / "drafts"
    (d / f"{date_tag}-launch-post.md").write_text(drafts.render_launch(Path(export_dir)), encoding="utf-8", newline="\n")
    (d / f"{date_tag}-weekend-report.md").write_text(drafts.render_weekend(Path(export_dir)), encoding="utf-8", newline="\n")
    typer.echo(f"wrote drafts/{date_tag}-launch-post.md and drafts/{date_tag}-weekend-report.md")


@house_app.command("due")
def house_due(network: str = typer.Option("base"), dry_run: bool = typer.Option(False)):
    """WRITES TO CHAIN: send every house record whose slot is open now (METHODS section 7). Idempotent."""
    from . import housedue
    cov = None
    try:
        from . import coverage
        cov = coverage.coverage_bytes_for_window
    except ImportError:
        pass
    res = housedue.run_due(network, dry_run=dry_run, coverage_data=cov)
    typer.echo(json.dumps(res, indent=1))
    _house_log(network, res)
    if any(r.get("status") == "error" for r in res):
        raise typer.Exit(2)


@house_app.command("anchor")
def house_anchor(export_dir: str = typer.Argument(...), network: str = typer.Option("base"),
                 dry_run: bool = typer.Option(False)):
    """WRITES TO CHAIN: put the SHA-256 of an export's manifest on the record (schema 3, once per day)."""
    import hashlib
    from datetime import date as _date
    from pathlib import Path

    from . import commits, housecommit
    if not housecommit.deployed(network):
        typer.echo(json.dumps({"status": "not_deployed", "network": network}))
        return
    p = Path(export_dir)
    h = hashlib.sha256((p / "manifest.json").read_bytes()).digest()
    d = _date.fromisoformat(p.name)
    wid = commits.window_id(commits.KIND_DAY, d)
    from datetime import UTC, datetime
    day_start = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)   # sent on its export date
    res = housecommit.commit(network, "anchor", None, wid, commits.SCHEMA_ANCHOR, commits.encode_anchor(h, d),
                             dry_run=dry_run, since_ms=day_start)
    typer.echo(json.dumps(res))
    _house_log(network, [res])


@app.command("check-house")
def check_house(export_dir: str = typer.Argument(...)):
    """Exit 3 when the export reports a missing house record (the Monday check)."""
    from pathlib import Path
    doc = json.loads((Path(export_dir) / "house_checks.json").read_text(encoding="utf-8"))
    missing = doc.get("house_commit_missing", [])
    typer.echo(json.dumps(missing, indent=1))
    if missing:
        raise typer.Exit(3)


if __name__ == "__main__":
    app()
