"""Static site from one export directory (site/build/). Plain HTML and CSS; one small script for the form.

Open probabilities never appear: the board and forecaster pages are built from resolved windows only, and
open windows show who committed, never what.
"""

from __future__ import annotations

import csv
import html
import io
import json
import shutil
from pathlib import Path

import markdown

from . import config, identity

NAV = [("index.html", "Overview"), ("absorb.html", "Absorb"), ("tape.html", "Weekend tape"),
       ("board.html", "Board"), ("commit.html", "Put a call on the record"), ("registry.html", "Registry"),
       ("methods.html", "Methods"), ("data.html", "Data")]
LUCK = ("With a few dozen windows, skill and luck cannot yet be told apart. Ranks use a lower confidence "
        "bound and a minimum of {n} scored windows, which reduces, but does not remove, the chance that a "
        "rank reflects luck. With many forecasters, the best of them will look skilled by chance.")


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def short(a: str) -> str:
    return a[:6] + "…" + a[-4:] if a and len(a) > 12 else (a or "")


def fnum(x, nd=2, pct=False, sign=False) -> str:
    if x is None or x == "":
        return '<span class="muted">–</span>'
    v = float(x) * (100 if pct else 1)
    s = f"{v:+,.{nd}f}" if sign else f"{v:,.{nd}f}"
    return s + ("%" if pct else "")


def usd(x) -> str:
    if x is None or x == "":
        return '<span class="muted">–</span>'
    v = float(x)
    if v >= 1e6:
        return f"${v / 1e6:,.2f}M"
    if v >= 1e3:
        return f"${v / 1e3:,.1f}k"
    return f"${v:,.0f}"


def page(name: str, title: str, body: str, as_of: str) -> str:
    nav = "".join(f'<a href="{href}"{" class=on" if href == name else ""}>{esc(label)}</a>' for href, label in NAV)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(identity.NAME)}</title>
<meta name="description" content="Calls on the record for tokenized stocks on Base, the weekend tape, and what these markets can absorb. Measurements, not verdicts.">
<link rel="stylesheet" href="style.css"></head>
<body><header class="top"><div class="inner"><a class="brand" href="index.html">{esc(identity.NAME)}</a><nav>{nav}</nav></div></header>
<main>{body}</main>
<footer><div class="inner">Data as of {esc(as_of)}. Every number is replayable from the published inputs (<a href="data.html">data</a>, <a href="methods.html">methods</a>, <a href="{identity.REPO_URL}">code</a>).
Measurements, not verdicts; nothing here is advice. Coinbase tokenized stocks are offered only to persons in eligible jurisdictions outside the United States.</div></footer>
</body></html>
"""


def table(headers: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    th = "".join(f'<th{" class=num" if num else ""}>{esc(h)}</th>' for h, num in headers)
    trs = "".join("<tr>" + "".join(f'<td{" class=num" if headers[i][1] else ""}>{c}</td>' for i, c in enumerate(row))
                  + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8"))))


def read_json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def build_site(export_dir: Path, out: Path) -> list[str]:
    export_dir, out = Path(export_dir), Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "f").mkdir(parents=True)
    (out / "data").mkdir()
    static = config.ROOT / "site" / "static"
    for f in static.iterdir():
        shutil.copy(f, out / f.name)
    manifest = read_json(export_dir / "manifest.json", {})
    as_of = manifest.get("as_of_utc", "?")
    tokens = json.loads((config.config_dir() / "tokens.json").read_text(encoding="utf-8"))
    sym = {t["address"]: t["symbol"] for t in tokens["tokens"]}
    names = {t["address"]: t.get("name") for t in tokens["tokens"]}
    board = read_json(export_dir / "leaderboard.json", {"forecasters": [], "min_windows": 5})
    windows = read_json(export_dir / "windows.json", {"windows": []})["windows"]
    open_w = read_json(export_dir / "open.json", {"windows": []})["windows"]
    usage = read_json(export_dir / "usage.json", {})
    tape = read_csv(export_dir / "tape.csv")
    absorb = read_json(export_dir / "absorb.json", None)
    house_checks = read_json(export_dir / "house_checks.json", {"house_commit_missing": []})
    pages: dict[str, str] = {}

    # copy the export's data files under data/ (the site serves the same bytes)
    for f in sorted(export_dir.rglob("*")):
        if f.is_file():
            dst = out / "data" / f.relative_to(export_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dst)
    shutil.copy(config.ROOT / "keys" / "export-key.json", out / "data" / "export-key.json")
    _form_json(out / "data" / "form.json", open_w, sym, names)

    # --- overview
    closed = [t for t in tape if t["kind"] == "1"]
    last_closed = max((t["window"] for t in closed if t["reopen_bps"]), default=None)
    lc_rows = [t for t in closed if t["window"] == last_closed]
    lc_label = next((w["label"] for w in windows if str(w["id"]) == str(last_closed)), "")
    from .tape import tape_stats
    ts = tape_stats(tape)
    n_tw = ts.get("n", 0)
    stats = (f'<div class="grid">'
             f'<div class="card stat"><div class="v">{len({t["window"] for t in closed})}</div><div class="k">closed windows measured since Aug 24</div></div>'
             f'<div class="card stat"><div class="v">{ts.get("median_reopen_bps", 0):,.0f} bps</div><div class="k">median move of the reference across a closed span ({n_tw} token-weekends with a usable DEX price)</div></div>'
             f'<div class="card stat"><div class="v">{ts.get("median_error_bps", 0):,.0f} bps</div><div class="k">median distance from the last-hour DEX price to the reopen value (same {n_tw})</div></div>'
             f'<div class="card stat"><div class="v">{usage.get("external_wallets", 0)}</div><div class="k">wallets with calls on the record (house wallets excluded)</div></div>'
             f'</div>')
    absorb_block = _absorb_summary(absorb, sym) if absorb else (
        '<p class="muted">Depth and lending snapshots are not in this export yet.</p>')
    body = (f'<h1>What these markets can absorb</h1>'
            f'<p class="lede">Coinbase-issued stock tokens on Base trade around the clock; their reference price '
            f'does not move on weekends and holidays. This site measures what that means: how much the pools '
            f'can absorb below the price, how far the tokens drift while the reference is frozen, and how well '
            f'anyone, on the record, calls the value the reference shows when it reopens.</p>'
            f'{absorb_block}<h2>The weekend tape</h2>{stats}'
            + (f'<h3>Last closed span: {esc(lc_label)}</h3>' + _tape_table(lc_rows, sym) if lc_rows else '')
            + f'<h2>The board</h2><p>{esc(LUCK.format(n=board["min_windows"]))}</p>'
            + _board_table(board["forecasters"][:10])
            + '<p><a href="board.html">Full board</a> · <a href="commit.html">Put a call on the record</a></p>')
    pages["index.html"] = page("index.html", "Overview", body, as_of)

    # --- board
    missing = house_checks.get("house_commit_missing", [])
    miss_html = "" if not missing else ('<div class="note">House records missing: ' + "; ".join(
        f'{esc(m["role"])} for {esc(m["label"])}' for m in missing) + "</div>")
    body = (f'<h1>The board</h1><p class="lede">Every forecaster with a record, scored against the reference feed '
            f'after each window closes. Brier score per token; skill against the DEX-implied baseline and against 50%.</p>'
            f'<div class="note">{esc(LUCK.format(n=board["min_windows"]))}</div>{miss_html}'
            + _board_table(board["forecasters"])
            + _baselines_block(read_json(export_dir / "baselines.json", {}))
            + '<p class="muted">House wallets (labelled) follow the published schedule and are excluded from every usage figure. '
              'Open windows show who committed, never what; probabilities appear here after the window resolves.</p>'
            + _open_table(open_w))
    pages["board.html"] = page("board.html", "Board", body, as_of)

    # --- forecaster pages
    for f in board["forecasters"]:
        c = f["committer"].lower()
        doc = read_json(export_dir / "forecasters" / f"{c}.json", {"windows": []})
        rows = []
        for w in doc["windows"]:
            for p in w["pairs"]:
                rows.append([str(w["window"]), esc(sym.get(p["token"], short(p["token"]))), fnum(p["p"], 2),
                             "up" if p["o"] == 1 else "down", fnum(p["brier"], 4), fnum(p["baseline_p"], 2),
                             fnum(p["baseline_brier"], 4)])
        tag = f'<span class="tag house">house: {esc(f["house_role"])}</span>' if f.get("house_role") else ""
        body = (f'<h1 class="mono">{esc(c)}{tag}</h1>'
                f'<div class="grid"><div class="card stat"><div class="v">{f["windows_scored"]}</div><div class="k">windows scored</div></div>'
                f'<div class="card stat"><div class="v">{fnum(f["brier"], 4)}</div><div class="k">mean Brier</div></div>'
                f'<div class="card stat"><div class="v">{fnum(f["skill_vs_dex"], 3, sign=True)}</div><div class="k">skill vs DEX-implied</div></div>'
                f'<div class="card stat"><div class="v">{fnum(f["edge_lcb"], 4, sign=True)}</div><div class="k">edge, lower bound</div></div></div>'
                '<h2>Resolved calls</h2>'
                + table([("window", False), ("token", False), ("p up", True), ("outcome", False), ("Brier", True),
                         ("DEX-implied p", True), ("DEX-implied Brier", True)], rows))
        pages[f"f/{c}.html"] = page("board.html", c, body.replace('href="', 'href="../').replace('href="../http', 'href="http'), as_of)

    # --- tape
    by_w: dict[str, list[dict]] = {}
    for t in closed:
        by_w.setdefault(t["window"], []).append(t)
    sections = []
    for wid in sorted(by_w, reverse=True):
        label = next((w["label"] for w in windows if str(w["id"]) == wid), wid)
        sections.append(f'<h3>{esc(label)}</h3>' + _tape_table(by_w[wid], sym))
    body = ('<h1>The weekend tape</h1><p class="lede">For every closed span since Aug 24: the frozen reference, '
            'the DEX price while it was frozen, and the value the reference showed at the reopen. gap = last-hour '
            'DEX price against the frozen value; reopen = the reference move across the span; error = reopen minus gap.</p>'
            + _scatter(closed) + "".join(sections))
    pages["tape.html"] = page("tape.html", "Weekend tape", body, as_of)

    # --- absorb
    pages["absorb.html"] = page("absorb.html", "Absorb", _absorb_page(absorb, sym), as_of)

    # --- commit
    pages["commit.html"] = page("commit.html", "Put a call on the record", _commit_page(open_w), as_of) \
        .replace("</body>", '<script src="commit.js"></script></body>')

    # --- registry
    feeds_cfg = json.loads(json.dumps(__import__("yaml").safe_load((config.config_dir() / "feeds.yaml").read_text(encoding="utf-8"))))
    feed_by_tok = {}
    for fd in feeds_cfg["feeds"]:
        if fd.get("token"):
            feed_by_tok.setdefault(fd["token"], []).append(fd)
    rows = []
    for t in sorted(tokens["tokens"], key=lambda t: (t["address"] not in feed_by_tok, t["symbol"])):
        fds = feed_by_tok.get(t["address"], [])
        mult = int(t["chain"]["ui_multiplier_wad"]) / 1e18 if t["chain"].get("ui_multiplier_wad") else None
        rows.append([esc(t["symbol"]), esc(t.get("name")), f'<span class="mono">{esc(t["address"])}</span>',
                     ", ".join(f'{esc(x["kind"])} <span class="mono">{esc(short(x["proxy"]))}</span>' for x in fds) if fds else '<span class="muted">none</span>',
                     fnum(mult, 6) if mult else "", "yes" if t["chain_matches_api"] else "no"])
    body = (f'<h1>Official token registry</h1><p class="lede">Every Coinbase-issued stock token on Base, from Coinbase\'s '
            f'published list ({esc(tokens["count"])} tokens, fetched {esc(tokens["fetched_at"])}), each checked on chain. '
            'Track tokens by address, never by symbol.</p>'
            + table([("symbol", False), ("name", False), ("address", False), ("reference feed", False),
                     ("multiplier", True), ("chain matches list", False)], rows))
    lk = read_json(export_dir / "lookalikes.json", {"tokens": []})
    if lk.get("tokens"):
        lrows = [[f'<span class="mono">{esc(t["address"])}</span>', esc(t.get("symbol")), esc(t.get("name")),
                  esc(", ".join(r["symbol"] for r in t.get("resembles", []))), esc(", ".join(t.get("match", []))),
                  "true"] for t in lk["tokens"]]
        body += ('<h2>Lookalikes seen</h2><p>Tokens on Base seen in public DEX data whose symbol or name matches an '
                 'official token but whose address is not on the official list (flag <code>R1_lookalike_symbol</code>). '
                 f'{esc(lk.get("rule", ""))}. The list records what the data showed and nothing about the issuers.</p>'
                 + table([("address", False), ("symbol", False), ("name", False), ("resembles", False),
                          ("match", False), ("R1_lookalike_symbol", False)], lrows))
    pages["registry.html"] = page("registry.html", "Registry", body, as_of)

    # --- methods
    md = (config.ROOT / "METHODS.md").read_text(encoding="utf-8")
    pages["methods.html"] = page("methods.html", "Methods", '<div class="prose">' + markdown.markdown(md, extensions=["tables"]) + "</div>", as_of)

    # --- data
    files = manifest.get("files", {})
    rows = [[f'<a href="data/{esc(k)}">{esc(k)}</a>', f'<span class="mono">{esc(v)}</span>'] for k, v in sorted(files.items())
            if not k.startswith("forecasters/")]
    sig = manifest.get("signature", {})
    body = ('<h1>Data</h1><p class="lede">Every file of this export, with its SHA-256. The manifest is signed '
            f'(Ed25519, key <span class="mono">{esc(sig.get("key_id"))}</span>, public half in <a href="data/export-key.json">export-key.json</a>) '
            'and its hash is put on the record on Base once a day. Code is Apache-2.0; data is CC-BY-4.0.</p>'
            + table([("file", False), ("sha256", False)], rows)
            + f'<p><a href="data/manifest.json">manifest.json</a> · methods version {esc(manifest.get("methods_version"))} · git {esc(manifest.get("git_commit", "")[:12])}</p>')
    pages["data.html"] = page("data.html", "Data", body, as_of)

    for name, content in pages.items():
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return sorted(pages)


def _form_json(path: Path, open_w: list[dict], sym: dict, names: dict) -> None:
    """What the form needs: open windows, the slate with symbols, the mainnet ledger and the project code."""
    import yaml
    led = {}
    lf = config.config_dir() / "ledger.yaml"
    if lf.exists():
        led = (yaml.safe_load(lf.read_text(encoding="utf-8")) or {}).get("base") or {}
    slate = sorted({t for w in open_w for t in w.get("slate", [])})
    doc = {"windows": [{k: w[k] for k in ("id", "label", "cutoff_ms", "cutoff_et")} for w in open_w],
           "slate": [{"address": t, "symbol": sym.get(t), "name": names.get(t)} for t in slate],
           "ledger": {"address": led["address"], "chain_id": 8453} if led.get("address") else None,
           "builder_codes": [led["builder_code"]] if led.get("builder_code") else []}
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _board_table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">No records have resolved yet.</p>'
    out = []
    for f in rows:
        c = f["committer"].lower()
        tag = f'<span class="tag house">house: {esc(f["house_role"])}</span>' if f.get("house_role") else ""
        out.append([esc(f["rank"] or ""), f'<a class="mono" href="f/{c}.html">{esc(short(c))}</a>{tag}',
                    esc(f["windows_scored"]), fnum(f["brier"], 4), fnum(f["skill_vs_dex"], 3, sign=True),
                    fnum(f["skill_vs_50"], 3, sign=True), fnum(f["edge_lcb"], 4, sign=True)])
    return table([("rank", True), ("forecaster", False), ("windows", True), ("Brier", True), ("skill vs DEX", True),
                  ("skill vs 50%", True), ("edge (lower bound)", True)], out)


def _baselines_block(b: dict) -> str:
    rows = []
    for label in ("closed", "daily"):
        x = b.get(label) or {}
        if not x.get("pairs"):
            continue
        rows.append([esc("closed spans (weekends, holidays)" if label == "closed" else "daily windows"),
                     esc(x["windows"]), esc(x["pairs"]), fnum(x["brier"], 4), fnum(x["skill_vs_50"], 3, sign=True),
                     fnum(x["direction_hit_rate"], 1, pct=True) if x.get("direction_hit_rate") is not None else "",
                     esc(x["pairs_void_dex"])])
    if not rows:
        return ""
    return ('<h2>The DEX-implied baseline since Aug 24</h2><p>Computed for every resolved window from the data, '
            'as if it had been on the record (it was not: house records start when the contract is deployed). '
            'This is the forecaster to beat.</p>'
            + table([("windows", False), ("count", True), ("token-windows", True), ("Brier", True),
                     ("skill vs 50%", True), ("direction right", True), ("DEX baseline void", True)], rows))


def _open_table(open_w: list[dict]) -> str:
    if not open_w:
        return ""
    rows = [[esc(w["label"]), esc(w["cutoff_et"]), esc("records counting" if w.get("open_for_records") else "cutoff passed, awaiting outcome"),
             esc(len(w.get("slate", []))), esc(len(w.get("committed", [])))] for w in open_w]
    return "<h2>Open windows</h2>" + table([("window", False), ("records count until", False), ("status", False),
                                            ("slate tokens", True), ("wallets committed", True)], rows)


def _tape_table(rows: list[dict], sym: dict) -> str:
    out = []
    for t in sorted(rows, key=lambda t: sym.get(t["token"], t["token"])):
        out.append([esc(sym.get(t["token"], short(t["token"]))), fnum(t["frozen_ref"], 2), fnum(t["twap_last_hour"], 2),
                    fnum(t["reopen_ref"], 2), fnum(t["gap_bps"], 0, sign=True), fnum(t["reopen_bps"], 0, sign=True),
                    fnum(t["tape_error_bps"], 0, sign=True), fnum(t["max_abs_gap_bps"], 0), esc(t["swaps_span"]),
                    usd(t["volume_span_usd"]), fnum(t["alt_247_ref"], 2), esc(t["void"] or "")])
    return table([("token", False), ("frozen ref", True), ("DEX last hour", True), ("reopen ref", True),
                  ("gap bps", True), ("reopen bps", True), ("error bps", True), ("max gap bps", True),
                  ("swaps", True), ("volume", True), ("24/7 feed", True), ("void", False)], out)


def _scatter(rows: list[dict]) -> str:
    pts = [(float(t["gap_bps"]), float(t["reopen_bps"])) for t in rows if t["gap_bps"] and t["reopen_bps"] and not t["void"]]
    if len(pts) < 3:
        return ""
    lim = max(50.0, max(max(abs(x), abs(y)) for x, y in pts) * 1.1)
    W, H, M = 520, 360, 40

    def sx(x):
        return M + (x + lim) / (2 * lim) * (W - 2 * M)

    def sy(y):
        return H - M - (y + lim) / (2 * lim) * (H - 2 * M)
    dots = "".join(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3" fill="var(--accent)" fill-opacity="0.6"/>' for x, y in pts)
    return (f'<figure><svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px" role="img" '
            f'aria-label="Reopen move against the last-hour DEX gap, in basis points">'
            f'<line x1="{sx(-lim)}" y1="{sy(-lim)}" x2="{sx(lim)}" y2="{sy(lim)}" stroke="var(--line)" stroke-dasharray="4 4"/>'
            f'<line x1="{M}" y1="{sy(0)}" x2="{W - M}" y2="{sy(0)}" stroke="var(--line)"/>'
            f'<line x1="{sx(0)}" y1="{M}" x2="{sx(0)}" y2="{H - M}" stroke="var(--line)"/>{dots}'
            f'<text x="{W - M}" y="{sy(0) - 6}" text-anchor="end">gap (DEX last hour vs frozen), bps</text>'
            f'<text x="{sx(0) + 6}" y="{M + 10}">reopen move, bps</text></svg>'
            f'<figcaption class="muted">Each dot is one token in one closed span. On the dashed line, the weekend DEX '
            f'price matched the reopen value exactly. {len(pts)} points.</figcaption></figure>')


def _absorb_summary(absorb: dict, sym: dict) -> str:
    rows = absorb.get("tokens", [])
    if not rows:
        return '<p class="muted">No depth snapshot yet.</p>'
    trs = []
    for s in ("5", "10", "20"):
        d = sum((x.get("absorb_5pct_below_usd") or {}).get(s) or 0 for x in rows)
        lq = sum((x.get("liquidation_flow_usd") or {}).get(s) or 0 for x in rows)
        uw = sum((x.get("underwater_debt_usd") or {}).get(s) or 0 for x in rows)
        short_n = sum(1 for x in rows if ((x.get("liquidation_flow_usd") or {}).get(s) or 0) >
                      ((x.get("absorb_5pct_below_usd") or {}).get(s) or 0))
        trs.append([f"{s}%", usd(lq), usd(d), usd(uw), esc(short_n)])
    tot = (absorb.get("lending_totals") or {}).get("total") or {}
    coll, debt = tot.get("collateral_usd"), tot.get("debt_usd")
    return (f'<div class="grid"><div class="card stat"><div class="v">{usd(debt)}</div><div class="k">USDC borrowed against stock tokens (Aave V4, Morpho)</div></div>'
            f'<div class="card stat"><div class="v">{usd(coll)}</div><div class="k">stock collateral enabled behind it</div></div></div>'
            '<h3>If the reference reopened lower, per token and summed</h3>'
            + table([("shock", False), ("liquidation flow", True), ("pool depth in the 5% below", True),
                     ("underwater debt", True), ("tokens where flow exceeds depth", True)], trs)
            + f'<p class="muted">Snapshot at block {esc(absorb.get("block"))} ({esc(absorb.get("at_et"))}). Each token is '
              f'shocked alone, at the oracle its lending markets read. {esc(absorb.get("coverage_note", ""))} '
              '<a href="absorb.html">Per token</a>.</p>')


def _absorb_page(absorb: dict | None, sym: dict) -> str:
    head = ('<h1>What these markets can absorb</h1><p class="lede">Downward pool depth for each token, set against '
            'the collateral lending markets on Base would liquidate if the price their oracle reads moved down 5%, '
            '10% or 20%. While the reference is frozen nothing can be liquidated: the flow arrives at the reopen, '
            'at the gap price. Measures onchain absorption only.</p>')
    if not absorb:
        return head + '<p class="muted">No snapshot in this export yet.</p>'
    rows = []
    for x in absorb.get("tokens", []):
        a, lq, uw = x.get("absorb_5pct_below_usd") or {}, x.get("liquidation_flow_usd") or {}, x.get("underwater_debt_usd") or {}
        rows.append([esc(sym.get(x["token"], short(x["token"]))), usd(x.get("move_1pct_usd")), usd(x.get("move_2pct_usd")),
                     fnum(x.get("impact_10k_bps"), 1), fnum(x.get("impact_100k_bps"), 1),
                     usd(a.get("10")), usd(lq.get("10")), usd(uw.get("10")), usd(a.get("20")), usd(lq.get("20")),
                     esc(x.get("tier", "")), esc(", ".join(x.get("flags", [])))])
    return (head + f'<p class="muted">Block {esc(absorb.get("block"))} ({esc(absorb.get("at_et"))}). {esc(absorb.get("coverage_note", ""))}</p>'
            + table([("token", False), ("down 1%", True), ("down 2%", True), ("$10k impact bps", True),
                     ("$100k impact bps", True), ("absorb @10%", True), ("liq. flow @10%", True), ("underwater @10%", True),
                     ("absorb @20%", True), ("liq. flow @20%", True), ("tier", False), ("flags", False)], rows)
            + _markets_table(absorb.get("markets", []), sym))


def _markets_table(markets: list[dict], sym: dict | None = None) -> str:
    if not markets:
        return ""
    sym = sym or {}
    rows = [[esc(m.get("protocol")), esc(m.get("market")), esc(m.get("collateral_symbol") or sym.get(m.get("token"), "")),
             usd(m.get("collateral_usd")),
             usd(m.get("debt_usd")), esc(m.get("positions")), esc(m.get("oracle_note", "")), esc(m.get("status", ""))]
            for m in markets]
    return "<h2>Lending markets read</h2>" + table([("protocol", False), ("market", False), ("collateral", False),
                                                  ("collateral value", True), ("debt", True), ("positions", True),
                                                  ("oracle", False), ("status", False)], rows)


def _commit_page(open_w: list[dict]) -> str:
    return ('<h1>Put a call on the record</h1>'
            '<p class="lede">One transaction to a contract that holds no funds and stores nothing: it emits your '
            'probabilities, per token, that the reference value ends the window above where it started. After the '
            'window closes, the record is scored against the Chainlink reference feed. The first record per wallet '
            'and window is the scored one.</p>'
            '<div class="note">This records a forecast. It does not touch any token, route anything or move any value; '
            'the transaction carries no ETH beyond gas. Your probabilities appear on the board only after the window resolves.</div>'
            '<div class="card"><p><label for="window">Window</label><br><select id="window"></select></p>'
            '<div id="tokens"></div><p><button class="primary" id="commit">Put it on the record</button></p>'
            '<p id="status" class="muted"></p><p class="muted">Contract <span class="mono" id="ledger"></span></p></div>'
            '<h2>For agents</h2><p>Use the TypeScript client (<code>commitCalls</code>) or send '
            '<code>commit(uint32 windowId, uint16 1, bytes data)</code> yourself; the encoding is in '
            '<a href="methods.html">METHODS section 4</a>. Append your own Builder Code in the ERC-8021 suffix; it is kept.</p>'
            '<h2>House schedule</h2><p>The project\'s own forecasters commit once per window (METHODS section 7). '
            'Daily windows: null, persistence and DEX-implied in the hour before 20:00 ET. Closed spans: null and '
            'persistence after the Friday close, DEX-implied in the two hours before the cutoff (Sunday 16:00 to '
            '18:00 ET), and the coverage call within two hours of the close. All house wallets are labelled '
            'and excluded from every usage figure.</p>')
