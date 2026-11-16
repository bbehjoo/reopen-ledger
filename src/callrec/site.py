"""Static site from one export directory (site/build/). Plain HTML and CSS, self-hosted fonts, two small
scripts: site.js (clock, reveals, shock toggle; reads data embedded in the page) and commit.js (the form).

Open probabilities never appear: the board and forecaster pages are built from resolved windows only, and
open windows show who committed, never what. The site is a function of the export: times shown are
anchored on the export's as_of, and the browser only places "now" against them.
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import markdown

from . import config, identity

NAV = [("agents.html", "For agents"), ("live.html", "Live"), ("board.html", "Board"),
       ("methods.html", "Methods"), ("data.html", "Data")]
CTA = ("commit.html", "Predict the reopen")
DESCRIPTION = ("Predict which way tokenized stocks reopen after the weekend. One transaction on Base, no stake, "
               "scored against Chainlink at the reopen. Plus the data on what a frozen weekend price means for "
               "lending markets. Measurements, not verdicts.")
TEMPLATE_URL = "https://github.com/bbehjoo/reopen-ledger-agent"
FEATURED = ("NVDAc", "TSLAc", "AAPLc", "GOOGLc", "MSFTc", "METAc", "AMZNc")
MARK = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="var(--accent)"/>'
        '<path d="M7 19.5h10.5L25 10.5" fill="none" stroke="var(--accent-ink)" stroke-width="3" stroke-linecap="round" '
        'stroke-linejoin="round"/><circle cx="25" cy="10.5" r="2.6" fill="var(--accent-ink)"/></svg>')
LUCK = ("With a few dozen windows, skill and luck cannot yet be told apart. Ranks need {n} scored windows and "
        "discount lucky streaks, which reduces, but does not remove, the chance that a rank reflects luck. With "
        "many forecasters, the best of them will look skilled by chance.")


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


def page(name: str, title: str, body: str, as_of: str, root: str = "", landing: bool = False, og: str = "og.png",
         url: str | None = None) -> str:
    """One page. `root` prefixes local links for pages in subfolders; `body` is wrapped unless `landing`."""
    nav = "".join(f'<a href="{root}{href}"{" class=on" if href == name else ""}>{esc(label)}</a>' for href, label in NAV)
    full = identity.NAME if landing else f"{title} | {identity.NAME}"
    if not landing:
        m = re.match(r'(<h1[^>]*>.*?</h1>(?:<p class="lede">.*?</p>)?)', body, re.DOTALL)
        if m:
            body = f'<div class="page-head">{m.group(1)}</div>' + body[m.end():]
    main = (f'<main id="main">{body}</main>' if landing
            else f'<main id="main" class="inner"><div class="wrap">{body}</div></main>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full)}</title>
<meta name="description" content="{esc(DESCRIPTION)}">
<meta name="theme-color" content="#0b0c0e">
<meta property="og:type" content="website"><meta property="og:site_name" content="{esc(identity.NAME)}">
<meta property="og:title" content="{esc(full)}"><meta property="og:description" content="{esc(DESCRIPTION)}">
<meta property="og:url" content="{identity.SITE_URL}{url if url is not None else ('' if name == 'index.html' else name)}">
<meta property="og:image" content="{identity.SITE_URL}{og}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{identity.SITE_URL}{og}">
<link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
<link rel="preload" href="{root}fonts/Geist-Variable.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{root}style.css">
<script>document.documentElement.classList.add("js")</script></head>
<body><a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap"><a class="brand" href="{root}index.html">{MARK}{esc(identity.NAME)}</a><nav aria-label="Pages">{nav}</nav>
<a class="btn primary small" href="{root}{CTA[0]}">{esc(CTA[1])}</a></div></header>
{main}
<footer><div class="wrap"><p>Data as of {esc(as_of)}. Every number is replayable from the published inputs.
Measurements, not verdicts; nothing here is advice. Coinbase tokenized stocks are offered only to persons in eligible jurisdictions outside the United States.</p>
<div class="links"><a href="{root}data.html">Data</a><a href="{root}methods.html">Methods</a><a href="{root}registry.html">Registry</a><a href="{identity.REPO_URL}">Code</a></div></div></footer>
{f'<script src="{root}commit.js" defer></script>' if landing else ""}<script src="{root}site.js" defer></script>
</body></html>
"""


HOUSE_NAMES = {"null": "Coin Flip", "persistence": "Frozen Price", "dex_implied": "Weekend DEX", "coverage": "Coverage",
               "anchor": "Anchor"}


def _badges(export_dir: Path, board: dict, open_w: list[dict], out: Path) -> set[str]:
    """badge/<wallet>.json in the shields.io endpoint format, for every scored forecaster ("beat the market k/n":
    windows where its mean Brier was below the Weekend DEX baseline's on the same pairs) and every wallet with a
    record in an open window ("on the record")."""
    made = set()
    d = out / "badge"
    d.mkdir(parents=True, exist_ok=True)

    def write(c: str, message: str, good: bool) -> None:
        doc = {"schemaVersion": 1, "label": identity.NAME, "message": message,
               "color": "ff6a2b" if good else "636973", "labelColor": "14161a"}
        (d / f"{c}.json").write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        made.add(c)

    for f in board.get("forecasters", []):
        c = f["committer"].lower()
        wins = [w for w in read_json(export_dir / "forecasters" / f"{c}.json", {"windows": []})["windows"] if w.get("pairs")]
        beat = sum(1 for w in wins if sum(p["brier"] for p in w["pairs"]) < sum(p["baseline_brier"] for p in w["pairs"]))
        write(c, f"beat the market {beat}/{len(wins)}" if wins else "on the record", bool(wins) and beat * 2 >= len(wins))
    for w in open_w:
        for c in w.get("committed", []):
            if c.lower() not in made:
                write(c.lower(), "on the record", True)
    return made


def _badge_img(c: str) -> str:
    from urllib.parse import quote
    return "https://img.shields.io/endpoint?url=" + quote(f"{identity.SITE_URL}badge/{c}.json", "")


def _badge_md(c: str) -> str:
    return f"[![{identity.NAME}]({_badge_img(c)})]({identity.SITE_URL}f/{c}.html)"


def _share(text: str, url: str) -> str:
    """An X compose link (opens the poster's own account; nothing is posted from here)."""
    from urllib.parse import urlencode
    return "https://x.com/intent/post?" + urlencode({"text": text, "url": url}).replace("&", "&amp;")


def house_tag(role: str | None) -> str:
    """The house forecasters are the rivals to beat; their published role stays in the data."""
    if not role:
        return ""
    return f'<span class="tag house" title="house wallet: {esc(role)}">{esc(HOUSE_NAMES.get(role, role))}</span>'


def head(title: str, lede: str = "", extra: str = "") -> str:
    """The title block of an inner page."""
    return (f'<div class="page-head"><h1>{title}</h1>' + (f'<p class="lede">{lede}</p>' if lede else "")
            + extra + "</div>")


def _et_label(ms: int) -> str:
    from .calendar import tz
    d = datetime.fromtimestamp(ms / 1000, tz())
    return d.strftime("%a %b ") + str(d.day) + d.strftime(", %H:%M ET")


def _spans(as_of_ms: int) -> dict:
    """Closed spans (freeze to reopen) from a week before the export to eight weeks after it."""
    from .calendar import tz, windows_between
    d0 = datetime.fromtimestamp(as_of_ms / 1000, tz()).date()
    out = [{"start": w.start_ms, "reopen": w.reopen_ms, "start_et": _et_label(w.start_ms),
            "reopen_et": _et_label(w.reopen_ms)}
           for w in windows_between(d0 - timedelta(days=7), d0 + timedelta(days=56)) if w.kind == 1 and w.reopen_ms]
    return {"spans": out}


def _week(as_of_ms: int, spans: list[dict]) -> str:
    """Seven days, Monday 00:00 ET onward, holding the freeze at or after the export; frozen spans hatched."""
    from .calendar import tz
    nxt = next((s for s in spans if s["reopen"] > as_of_ms), None)
    if not nxt:
        return ""
    z = tz()
    s0 = datetime.fromtimestamp(nxt["start"] / 1000, z)
    mon = datetime(s0.year, s0.month, s0.day, tzinfo=z) - timedelta(days=s0.weekday())
    a = int(mon.timestamp() * 1000)
    b = int((mon + timedelta(days=7)).timestamp() * 1000)
    pct = lambda ms: max(0.0, min(100.0, (ms - a) / (b - a) * 100))  # noqa: E731
    days = "".join(f'<div class="day" style="left:{pct(int((mon + timedelta(days=i)).timestamp() * 1000)):.3f}%">'
                   f'{(mon + timedelta(days=i)).strftime("%a")}</div>' for i in range(7))
    frz = "".join(f'<div class="frz" style="left:{pct(s["start"]):.3f}%;width:{pct(s["reopen"]) - pct(s["start"]):.3f}%">'
                  f'<span>frozen</span></div>' for s in spans if s["reopen"] > a and s["start"] < b)
    return (f'<div class="week rv"><div class="bar" data-from="{a}" data-to="{b}" role="img" '
            f'aria-label="The week of {esc(nxt["start_et"])}: the reference is frozen in the hatched span">'
            f'{days}{frz}<div class="now" hidden></div></div></div>')


def _hero_board(export_dir: Path, as_of: str, open_w: list[dict] | None = None) -> str:
    """The freeze clock over a working mini prediction card: four featured stocks of the open slate (or of the
    feeds, when no window is open), each with its Chainlink reference value and a probability slider. The
    button carries the picks to the full form; nothing is sent from here."""
    feeds = {}
    for f in sorted((export_dir / "feed").glob("*.json")):
        d = read_json(f, {})
        ref = d.get("reference") or {}
        if ref.get("value") is not None:
            feeds[d.get("symbol", "")] = (ref["value"], d.get("token", ""))
    slate_syms = None
    for w in open_w or []:
        if w.get("open_for_records"):
            slate_syms = {s for s, (_, t) in feeds.items() if t in set(w.get("slate", []))}
            break
    pick = [s for s in FEATURED if s in feeds and (slate_syms is None or s in slate_syms)][:4]
    names = {t["address"]: t.get("name") for t in json.loads((config.config_dir() / "tokens.json").read_text(encoding="utf-8"))["tokens"]}
    rows = "".join(
        f'<div class="pick" data-sym="{esc(s)}" data-token="{esc(feeds[s][1].lower())}"><div class="lbl"><span class="s">{esc(s)}</span>'
        f'<span class="n">{esc((names.get(feeds[s][1]) or "").replace(" Inc.", "").replace(" Corporation", ""))} '
        f'&middot; ${feeds[s][0]:,.2f}</span></div>'
        f'<div class="tap" role="group" aria-label="{esc(s)} reopens"><button type="button" data-v="35" aria-pressed="false">Lower</button>'
        f'<button type="button" data-v="65" aria-pressed="false">Higher</button></div></div>' for s in pick)
    return (f'<div class="panel board-live" aria-live="off"><div class="head"><div>'
            f'<span class="state" id="state"><i></i><span>Reference</span></span>'
            f'<div class="clock" id="clock">Fri 20:00 ET</div><div class="clock-k" id="clock-k">The reference freezes every Friday 20:00 ET and reopens Sunday 20:00 ET.</div></div></div>'
            f'<div class="pick-q">Where does each one reopen? Tap one, skip the rest.</div>{rows}'
            f'<div class="pick-go"><a class="btn primary" id="hp-go" href="{CTA[0]}">Commit on Base <span class="arr">&rarr;</span></a>'
            f'<span>One transaction, no stake. '
            + ('Free with Coinbase Wallet / Base app; other wallets pay a tiny gas fee. ' if os.environ.get("PAYMASTER_URL") else 'Gas only. ')
            + f'<a href="{CTA[0]}" id="hp-adv">Advanced: set exact odds</a></span></div>'
            f'<p class="pick-status" id="hp-status" role="status"></p>'
            f'<div class="foot">Chainlink reference values on Base, read {esc(_utc_label(as_of))}.</div></div>')


def _utc_label(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return iso
    return d.strftime("%b ") + str(d.day) + d.strftime(", %H:%M UTC")


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
        (shutil.copytree if f.is_dir() else shutil.copy)(f, out / f.name)
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
    _form_json(out / "data" / "form.json", open_w, sym, names, tape, windows)

    # --- overview
    closed = [t for t in tape if t["kind"] == "1"]
    from .tape import tape_stats
    ts = tape_stats(tape)
    as_of_ms = int(datetime.fromisoformat(as_of.replace("Z", "+00:00")).timestamp() * 1000) if as_of != "?" else 0
    pages["index.html"] = page("index.html", "Overview", _landing(
        export_dir, as_of, as_of_ms, closed, ts, absorb, sym, read_json(export_dir / "baselines.json", {}),
        board, usage, open_w), as_of, landing=True)

    # --- result cards for the latest scored window (the Sunday reveal)
    from . import cards
    made = cards.build_cards(export_dir, out)
    reveal = ""
    for item in (made or {}).get("windows", []):
        when = cards._when(item["window"]["label"])
        text = (f"{when}: who beat the weekend market? Predictions on Base, scored against Chainlink at the reopen."
                if item["window"].get("kind") == 1 else f"{when}: who called the session? Scored against Chainlink.")
        reveal += (f'<div class="reveal"><img src="{item["card"]}" width="1200" height="675" '
                   f'alt="Results for {esc(when)}: each forecaster, how many stocks it called, and its score against Weekend DEX and Coin Flip">'
                   f'<a class="btn small" href="{_share(text, identity.SITE_URL + "board.html")}">Share on X</a></div>')
    badges = _badges(export_dir, board, open_w, out)

    # --- board
    missing = house_checks.get("house_commit_missing", [])
    miss_html = "" if not missing else ('<div class="note">House records missing: ' + "; ".join(
        f'{esc(m["role"])} for {esc(m["label"])}' for m in missing) + "</div>")
    baselines = read_json(export_dir / "baselines.json", {})
    body = (f'<h1>The board</h1><p class="lede">Every forecaster with a record, scored against Chainlink when each '
            f'window closes. Lower score is better; a coin flip scores 0.250.</p>'
            f'{_counter(usage)}{reveal}{_rivals_block(baselines)}{miss_html}'
            + '<h2>Forecasters</h2>' + _board_table(board["forecasters"])
            + f'<div class="note">{esc(LUCK.format(n=board["min_windows"]))}</div>'
            + _baselines_block(baselines)
            + '<p class="muted">House wallets (labelled) follow the published schedule and are excluded from every usage figure. '
              'Open windows show who committed, never what; probabilities appear here after the window resolves.</p>'
            + _open_table(open_w))
    pages["board.html"] = page("board.html", "Board", body, as_of, og=made.get("window_card", "og.png") if made else "og.png")

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
        tag = house_tag(f.get("house_role"))
        card = (made or {}).get("forecaster_cards", {}).get(c)
        mine = (made or {}).get("latest", {}).get(c)
        share = ""
        if c in badges:
            md = _badge_md(c)
            share += (f'<div class="badge-row"><img src="{esc(_badge_img(c))}" alt="Reopen Ledger badge" height="20">'
                      f'<code>{esc(md)}</code></div>')
        if card and mine:
            line = (f"Called {mine['called']} of {mine['decided']} at the reopen. " if mine["decided"] else "On the record. ")
            line += ("Beat the weekend market. " if mine["score"] < mine["dex"] else "")
            share += (f'<div class="reveal"><img src="{card}" width="1200" height="675" alt="{esc(line)}">'
                     f'<a class="btn small" href="{_share(line + "Can your agent do better?", identity.SITE_URL + f"f/{c}.html")}">Share on X</a></div>')
        body = (f'<h1 class="mono">{esc(c)}{tag}</h1>{share}'
                f'<div class="grid"><div class="card stat"><div class="v">{f["windows_scored"]}</div><div class="k">windows scored</div></div>'
                f'<div class="card stat"><div class="v">{fnum(f["brier"], 4)}</div><div class="k">score (lower is better; a coin flip scores 0.250)</div></div>'
                f'<div class="card stat"><div class="v">{fnum(f["skill_vs_dex"], 3, sign=True)}</div><div class="k">vs Weekend DEX</div></div>'
                f'<div class="card stat"><div class="v">{fnum(f["edge_lcb"], 4, sign=True)}</div><div class="k">edge, luck discounted</div></div></div>'
                '<h2>Resolved calls</h2>'
                + table([("window", False), ("token", False), ("p up", True), ("outcome", False), ("Brier", True),
                         ("DEX-implied p", True), ("DEX-implied Brier", True)], rows))
        body = body.replace('href="', 'href="../').replace('href="../http', 'href="http').replace('src="cards/', 'src="../cards/')
        pages[f"f/{c}.html"] = page("board.html", c, body, as_of, root="../", og=card or "og.png", url=f"f/{c}.html")

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
            + '<div class="panel chart narrow">' + _scatter(closed) + '</div>' + "".join(sections))
    pages["tape.html"] = page("tape.html", "Weekend tape", body, as_of)

    # --- absorb
    pages["absorb.html"] = page("absorb.html", "Absorb", _absorb_page(absorb, sym), as_of)

    # --- commit
    pages["commit.html"] = page("commit.html", "Predict the reopen", _commit_page(open_w), as_of) \
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
    pages["agents.html"] = page("agents.html", "For agents", _agents_page(), as_of)
    pages["live.html"] = page("live.html", "Live", _live_page(export_dir, absorb, sym) + (f'<script type="application/json" id="spans">{json.dumps(_spans(as_of_ms))}</script>' if as_of_ms else ""), as_of)

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


def _ledger() -> dict:
    import yaml
    lf = config.config_dir() / "ledger.yaml"
    return ((yaml.safe_load(lf.read_text(encoding="utf-8")) or {}).get("base") or {}) if lf.exists() else {}


def _short_usd(v: float) -> tuple[str, str]:
    """($7.27, M) style split for display numbers."""
    if v >= 1e6:
        return f"${v / 1e6:,.2f}", "M"
    if v >= 1e3:
        return f"${v / 1e3:,.0f}", "k"
    return f"${v:,.0f}", ""


def _landing(export_dir: Path, as_of: str, as_of_ms: int, closed: list[dict], ts: dict, absorb: dict | None,
             sym: dict, baselines: dict, board: dict, usage: dict, open_w: list[dict] | None = None) -> str:
    sp = _spans(as_of_ms) if as_of_ms else {"spans": []}
    led = _ledger()
    n_weekends = len({t["window"] for t in closed})
    tot = ((absorb or {}).get("lending_totals") or {}).get("total") or {}
    debt_v, debt_u = _short_usd(tot.get("debt_usd") or 0)
    coll_v, coll_u = _short_usd(tot.get("collateral_usd") or 0)
    cb = baselines.get("closed") or {}
    hit = cb.get("direction_hit_rate")

    sk = cb.get("skill_vs_50")
    dsk = (baselines.get("daily") or {}).get("skill_vs_50")
    if sk is not None and sk > 0:
        h1 = '<span>The weekend market</span> <span>barely beats a <span class="accent">coin flip.</span></span>'
        nums = f"Its odds on the Sunday-night reopen score just {sk:.3f} better than a coin flip's"
    else:
        h1 = '<span>The weekend market</span> <span>is a <span class="accent">coin flip.</span></span>'
        nums = "Its odds on the Sunday-night reopen score no better than a coin flip's"
    if dsk is not None:
        nums += f"; on weekday closes, {abs(dsk):.3f} {'worse' if dsk < 0 else 'better'}."
    else:
        nums += "."
    hero = (f'<section class="hero"><div class="wrap">'
            f'<p class="kicker"><i class="live-dot"></i>Stocks trade all weekend on Base. The price lenders use is frozen.</p>'
            f'<h1>{h1}</h1>'
            f'<div class="intro">'
            f'<p class="lede"><b class="ask">Can your agent beat it?</b> {nums} Predict on chain, get scored by '
            f'Chainlink, and build a public record nobody can rewrite.</p>'
            f'<div class="cta-row"><a class="btn primary" href="agents.html">Plug in your agent <span class="arr">&rarr;</span></a>'
            f'<a class="btn" href="{CTA[0]}">{esc(CTA[1])}</a></div>{_counter(usage, small=True)}</div>'
            f'{_hero_board(export_dir, as_of, open_w)}</div></section>')

    tiles = (f'<div class="bento">'
             f'<div class="tile hot rv"><span class="k">Borrowed against stock tokens</span><div>'
             f'<div class="big">{debt_v}<small>{debt_u}</small></div>'
             f'<p>USDC lent on Aave and Morpho against tokenized stocks, by {int(tot.get("borrowers") or 0):,} borrowers. '
             f'While the reference is frozen nothing can be liquidated. It all lands at the reopen.</p></div></div>'
             f'<div class="tile s2 rv" style="--i:1"><div class="big">{n_weekends}</div><p>weekends and holidays measured since Aug 24, every token, every swap.</p></div>'
             f'<div class="tile s2 ink rv" style="--i:2"><div class="big">{ts.get("median_reopen_bps", 0) / 100:.2f}<small>%</small></div>'
             f'<p>median jump of the reference when it reopens.</p></div>'
             f'<div class="tile s3 ink rv" style="--i:1"><div class="big">{coll_v}<small>{coll_u}</small></div><p>stock collateral behind those loans, all priced by a feed that sleeps on weekends.</p></div>'
             f'<div class="tile s3 rv" style="--i:2"><div class="big">{ts.get("median_error_bps", 0) / 100:.2f}<small>%</small></div>'
             f'<p>median miss of the last-hour weekend DEX price against the reopen value.</p></div>'
             f'</div>')
    numbers = (f'<section class="band" id="why"><div class="wrap"><h2 class="rv">Why the reopen matters.</h2>'
               f'<p class="lede rv">Lending markets on Base price these stocks off the same frozen feed. Millions ride on '
               f'what it shows when it comes back.</p>{tiles}</div></section>')

    week = (f'<section class="band tight"><div class="wrap"><h2 class="rv">Three steps, every weekend.</h2>{_week(as_of_ms, sp["spans"])}'
            f'<div class="steps three">'
            f'<div class="rv"><b>Before Sun 18:00 ET</b><strong>Make your prediction</strong><p>Tap higher or lower for each stock, or let your agent set exact odds. Free to enter, nothing staked.</p></div>'
            f'<div class="rv" style="--i:1"><b>One transaction</b><strong>Commit it on Base</strong><p>It goes on the record in a contract that holds no funds. Nothing is staked; you pay gas only.</p></div>'
            f'<div class="rv" style="--i:2"><b>Sun 20:00 ET</b><strong>Get scored at the reopen</strong><p>Chainlink\'s price comes back and scores every prediction. The board ranks forecasters across weekends.</p></div>'
            f'</div></div></section>')

    absorb_sec = ""
    if absorb and absorb.get("tokens"):
        toks = []
        for x in absorb["tokens"]:
            d, lq = x.get("absorb_5pct_below_usd") or {}, x.get("liquidation_flow_usd") or {}
            toks.append({"s": sym.get(x["token"], short(x["token"])),
                         "depth": {k: round(d.get(k) or 0, 2) for k in ("5", "10", "20")},
                         "flow": {k: round(lq.get(k) or 0, 2) for k in ("5", "10", "20")}})
        toks.sort(key=lambda t: (-t["flow"]["20"], -t["depth"]["20"]))
        rows = "".join(f'<div class="row" data-i="{i}"><span class="s">{esc(t["s"])}</span><div class="bars">'
                       f'<div class="b depth"></div><div class="b flow"></div></div><span class="v"></span></div>'
                       for i, t in enumerate(toks))
        absorb_sec = (
            '<section class="band"><div class="wrap split"><div>'
            '<h2 class="rv">What if it reopens lower?</h2>'
            '<p class="lede rv">Pick a shock. We set the collateral that would be liquidated against the pool depth '
            'in the 5% below, token by token, from a snapshot of Base itself.</p>'
            '<div class="seg" role="group" aria-label="Shock size">'
            + "".join(f'<button type="button" data-s="{s}" aria-pressed="false">&minus;{s}%</button>' for s in ("5", "10", "20"))
            + f'</div><div class="readout"><div class="flow"><div class="big" id="ab-flow">{usd(sum(t["flow"]["20"] for t in toks))}</div><div class="k">liquidation flow</div></div>'
            f'<div><div class="big" id="ab-depth">{usd(sum(t["depth"]["20"] for t in toks))}</div><div class="k">pool depth in the 5% below</div></div></div>'
            f'<p class="shock-note" id="ab-note"></p>'
            f'<p><a href="absorb.html">Per token, per market &rarr;</a></p></div>'
            f'<div class="panel flows rv"><div class="legend"><span><i style="background:var(--line-2)"></i>pool depth</span>'
            f'<span><i style="background:var(--accent)"></i>liquidation flow</span></div>{rows}</div></div>'
            f'<script type="application/json" id="absorb-data">{json.dumps({"initial": "20", "tokens": toks})}</script></section>')

    tape_sec = (f'<section class="band"><div class="wrap split"><div>'
                f'<h2 class="rv">The weekend price is a hint, not an answer.</h2>'
                f'<p class="lede rv">How close does the DEX price get to where the reference reopens? Each dot is one token on one weekend. '
                f'On the dashed line, the weekend price called it exactly.</p>'
                f'<div class="facts rv">'
                f'<div><span>Token-weekends with a usable DEX price</span><strong>{ts.get("n", 0)}</strong></div>'
                + (f'<div><span>Weekend DEX price had the direction right</span><strong>{hit * 100:.0f}%</strong></div>' if hit is not None else "")
                + (f'<div><span>How much better than a coin flip its odds score</span><strong>{cb.get("skill_vs_50", 0):+.3f}</strong></div>' if cb else "")
                + f'<div><span>Largest reopen move seen</span><strong>{ts.get("max_reopen_bps", 0) / 100:.1f}%</strong></div>'
                f'</div><p style="margin-top:20px"><a href="tape.html">Every weekend, stock by stock &rarr;</a></p></div>'
                f'<div class="panel chart">{_scatter(closed, big=True)}</div></div></section>')

    code = ('<pre class="code"><span class="c">// one transaction, no value: probabilities per token for one window</span>\n'
            '<span class="k">import</span> { commitCalls, windowId } <span class="k">from</span> <span class="s">"./clients/ts"</span>;\n\n'
            '<span class="k">await</span> commitCalls({\n'
            '  wallet,\n'
            f'  ledger: <span class="s">"{esc(led.get("address", "0x..."))}"</span>,\n'
            f'  windowId: windowId(1, <span class="s">"{esc(_next_friday(sp["spans"], as_of_ms))}"</span>),\n'
            '  calls: [{ token: NVDAc, p: <span class="k">0.62</span> }, { token: TSLAc, p: <span class="k">0.41</span> }],\n'
            '});</pre>')
    chips = ""
    if led.get("address"):
        chips = (f'<div class="chips"><a class="chip" href="https://basescan.org/address/{esc(led["address"])}">CallLedger <b>{esc(short(led["address"]))}</b></a>'
                 f'<span class="chip">Builder Code <b>{esc(led.get("builder_code", ""))}</b></span>'
                 f'<span class="chip">Base mainnet</span></div>')
    agents = (f'<section class="band"><div class="wrap split"><div>'
              f'<h2 class="rv">Built for agents too.</h2>'
              f'<p class="lede rv">An agent predicts with one function call: same contract, same scoring, same board. '
              f'The contract holds no funds and moves nothing; it records the prediction and the reopen scores it.</p>{chips}'
              f'<div class="cta-row"><a class="btn primary" href="{CTA[0]}">{esc(CTA[1])} <span class="arr">&rarr;</span></a>'
              f'<a class="btn" href="board.html">See the board</a></div></div><div class="rv">{code}</div></div></section>')

    closer = ('<section class="band closer"><div class="wrap"><h2 class="rv">Don\'t trust the dashboard. Replay it.</h2>'
              '<div class="trust">'
              '<div class="rv"><strong>Signed</strong><p>Every daily export is signed, so any copy can be checked against the original.</p></div>'
              '<div class="rv" style="--i:1"><strong>Anchored</strong><p>The export hash goes on the record on Base once a day.</p></div>'
              '<div class="rv" style="--i:2"><strong>Replayable</strong><p>Every number rebuilds from public chain logs with one command.</p></div>'
              f'<div class="rv" style="--i:3"><strong>Open</strong><p>Code under Apache-2.0, data under CC BY 4.0. <a href="{identity.REPO_URL}">Read the code</a>.</p></div>'
              '</div></div></section>')
    spans_json = f'<script type="application/json" id="spans">{json.dumps(sp)}</script>'
    return hero + week + numbers + absorb_sec + tape_sec + agents + closer + spans_json


def _live_page(export_dir: Path, absorb: dict | None, sym: dict) -> str:
    """The freeze, live in the browser: each stock's DEX price now (DexScreener) against its Chainlink reference
    (read on Base), and what the lending markets would liquidate if the reference reopened at the DEX price,
    against the pool depth there. Lending positions and depth come from the export's snapshot and are dated;
    the prices are live. Nothing is sent; static/live.js does the reading."""
    import yaml
    if not absorb or not absorb.get("tokens"):
        return head("Live: the freeze", "No lending snapshot in this export yet.")
    feeds = {fd["token"].lower(): fd for fd in yaml.safe_load((config.config_dir() / "feeds.yaml").read_text(encoding="utf-8"))["feeds"]
             if fd.get("token") and fd.get("kind") == "24/5"}
    toks = []
    for x in absorb["tokens"]:
        a = x["token"].lower()
        f = read_json(export_dir / "feed" / f"{sym.get(x['token'], '')}.json", {}) or {}
        fd = feeds.get(a)
        toks.append({"s": sym.get(x["token"], short(a)), "a": a,
                     "proxy": fd["proxy"] if fd else None, "dec": int(fd.get("decimals", 8)) if fd else 8,
                     "ref": (f.get("reference") or {}).get("value"),
                     "flow": {k: round(((x.get("liquidation_flow_usd") or {}).get(k) or 0), 2) for k in ("5", "10", "20")},
                     "depth": {k: round(((x.get("absorb_5pct_below_usd") or {}).get(k) or 0), 2) for k in ("5", "10", "20")}})
    toks.sort(key=lambda t: t["s"])
    rows = "".join(f'<tr data-a="{t["a"]}"><td>{esc(t["s"])}</td><td class="num ref">&ndash;</td><td class="num dex">&ndash;</td>'
                   f'<td class="num gap">&ndash;</td><td class="num flow">&ndash;</td><td class="num depth">&ndash;</td>'
                   f'<td class="flag"></td></tr>' for t in toks)
    data = {"tokens": toks, "snapshot": {"block": absorb.get("block"), "at_et": absorb.get("at_et")}}
    return (
        head("Live: what lands at the reopen",
             "While the price lenders use is frozen, nothing can be liquidated. This page reads each stock's DEX "
             "price and its Chainlink price right now, and shows what the lending markets would liquidate if the "
             "price reopened at the DEX price, against the pool depth there to absorb it.")
        + '<div class="live-top"><span class="state" id="state"><i></i><span>Reference</span></span>'
          '<span class="clock" id="clock"></span><span class="clock-k" id="clock-k"></span></div>'
        + '<div class="readout live-sum"><div class="flow"><div class="big" id="lv-flow">&ndash;</div><div class="k">would be liquidated '
          'at the reopen, at today\'s DEX prices</div></div><div><div class="big" id="lv-depth">&ndash;</div>'
          '<div class="k">pool depth in the 5% below, there to absorb it</div></div></div>'
        + '<p class="shock-note" id="lv-note">Reading prices...</p>'
        + table([("stock", False), ("Chainlink now", True), ("DEX now", True), ("gap", True),
                 ("liquidation flow", True), ("depth", True), ("", False)], []).replace("<tbody></tbody>", f"<tbody>{rows}</tbody>")
        + f'<p class="muted" id="lv-meta">Prices: DexScreener (most liquid Base pool) and Chainlink on Base, read in your '
          f'browser, refreshed every minute. Lending positions and pool depth: the snapshot at block '
          f'{esc(absorb.get("block"))} ({esc(absorb.get("at_et"))}), interpolated between the 5%, 10% and 20% shocks '
          f'of <a href="absorb.html">the absorb page</a>. Each stock on its own, onchain absorption only.</p>'
        + f'<script type="application/json" id="live-data">{json.dumps(data)}</script>')


def _agents_page() -> str:
    """How an agent gets on the board: why, three steps, the MCP server, the rules that decide what counts."""
    led = _ledger()
    repo = identity.REPO_URL
    chips = ""
    if led.get("address"):
        chips = (f'<div class="chips"><a class="chip" href="https://basescan.org/address/{esc(led["address"])}">CallLedger <b>{esc(short(led["address"]))}</b></a>'
                 f'<span class="chip">Base mainnet, chain 8453</span><span class="chip">Our Builder Code <b>{esc(led.get("builder_code", ""))}</b></span></div>')
    mcp = ('{\n  "mcpServers": {\n    "reopen-ledger": {\n      "command": "node",\n'
           '      "args": ["/path/to/reopen-ledger/clients/ts/dist/src/mcp.js"]\n    }\n  }\n}')
    return (
        '<h1>Your agent on the board in 5 minutes.</h1>'
        '<p class="lede">Reopen Ledger is the weekend benchmark for stock-forecasting agents. Your agent commits a '
        'probability per stock before the cutoff, Chainlink scores it at the reopen, and the board ranks it against '
        'three rivals: Coin Flip, Frozen Price and Weekend DEX.</p>' + chips +
        '<div class="trust" style="margin-top:40px">'
        '<div><strong>Your attribution stays yours</strong><p>Your Builder Code rides in the same transaction, next to '
        'ours, so every prediction your agent makes stays attributed to your project.</p></div>'
        '<div><strong>A record nobody can rewrite</strong><p>Predictions are on chain before the outcome and scored against '
        'Chainlink. Every agent gets a public page to link anywhere.</p></div>'
        '<div><strong>Every trading day</strong><p>A window each weekday evening plus one across every weekend and holiday. '
        'One scheduled job covers them all.</p></div>'
        '<div><strong>Nothing at stake</strong><p>The contract holds no funds and moves nothing. Gas is the only cost, a '
        'fraction of a cent on Base.</p></div></div>'
        '<h2>Three steps, no server</h2>'
        '<div class="steps three">'
        f'<div><b>1. Use the template</b><strong>One click on GitHub</strong><p><a href="{TEMPLATE_URL}/generate">'
        'Create your repo from the agent template</a>. A workflow in it predicts once a day for every window that '
        'closes in the next 24 hours.</p></div>'
        '<div><b>2. Add your secrets</b><strong>Key and Builder Code</strong><p><code>PRIVATE_KEY</code> for a fresh '
        'Base wallet with a little ETH for gas, or no key at all with a Coinbase Developer Platform server account. '
        'Plus <code>BUILDER_CODES</code> with your own code.</p></div>'
        '<div><b>3. Start from a real strategy</b><strong>Then make it yours</strong><p>It starts as the Weekend DEX '
        'rival (the DEX price against Chainlink, read as odds) with a <code>CONFIDENCE</code> knob. Change it in '
        '<code>predict()</code>; a dry run from the Actions tab shows the exact transaction first.</p></div></div>'
        f'<div class="cta-row"><a class="btn primary" href="{TEMPLATE_URL}/generate">Use the template <span class="arr">&rarr;</span></a>'
        f'<a class="btn" href="{TEMPLATE_URL}">See the template</a></div>'
        '<h2>Or run it yourself</h2>'
        f'<pre class="code" style="margin-top:20px">git clone {repo}\ncd reopen-ledger/examples/agent && npm i\n\n'
        '<span class="c"># your wallet and your Builder Code</span>\n'
        'export PRIVATE_KEY=0x...  BUILDER_CODES=bc_yourcode\n\n'
        'npm run dry      <span class="c"># prints window, probabilities, calldata</span>\n'
        'npm start        <span class="c"># one transaction on Base</span>\n\n'
        '<span class="c"># or Python</span>\npython agent.py --dry-run</pre>'
        f'<p>Full guide, cron and GitHub Actions schedules: <a href="{repo}/tree/main/examples/agent">examples/agent</a>.</p>'
        '<h2>Prefer tools? Use the MCP server.</h2>'
        '<p>The client ships an MCP server with tools for the open windows, each token\'s published record and the '
        'commit encoding. Build it from a clone (<code>cd clients/ts &amp;&amp; npm i &amp;&amp; npm run build</code>) '
        'and add it to your MCP client:</p>'
        f'<pre class="code">{esc(mcp)}</pre>'
        '<h2>Show your record</h2>'
        '<p>Every forecaster gets a badge for its README and demo, live from the board: <em>on the record</em> from '
        'its first prediction, then <em>beat the market k/n</em> once windows are scored. Copy it from your '
        'forecaster page, or use this with your wallet address in lowercase:</p>'
        f'<pre class="code">{esc(_badge_md("0xYOUR_WALLET").replace("0xyour_wallet", "0xYOUR_WALLET"))}</pre>'
        '<h2>What counts</h2>'
        '<div class="facts">'
        '<div><span>A prediction counts if it is mined before the window\'s cutoff</span><strong>Sun 18:00 ET</strong></div>'
        '<div><span>The first prediction per wallet and window is the scored one</span><strong>1 per window</strong></div>'
        '<div><span>Predictions stay hidden until the window resolves, so nobody can copy them</span><strong>sealed</strong></div>'
        '<div><span>Ranks need five scored windows, and lucky streaks are discounted</span><strong>no luck ranks</strong></div>'
        '</div>'
        '<p class="muted" style="margin-top:20px">Encoding and scoring are specified in <a href="methods.html">METHODS</a> '
        'sections 4 and 5. The weekday cutoff is 20:00 ET; weekend and holiday cutoffs are two hours before the reopen.</p>'
        '<div class="cta-row"><a class="btn primary" href="board.html">See the board <span class="arr">&rarr;</span></a>'
        f'<a class="btn" href="{CTA[0]}">{esc(CTA[1])}</a></div>')


def _next_friday(spans: list[dict], as_of_ms: int) -> str:
    """The date a closed window is named by (its first day), for the code sample."""
    from .calendar import tz
    nxt = next((s for s in spans if s["reopen"] > as_of_ms), None)
    return datetime.fromtimestamp(nxt["start"] / 1000, tz()).date().isoformat() if nxt else "2026-11-20"


def _open_sigma(open_w: list[dict], tape: list[dict], windows: list[dict]) -> dict[int, float]:
    """The sigma the DEX-implied baseline (METHODS section 6) will use for each open window: 1.4826 x the
    median absolute tape error of earlier windows of the same kind that ended before it starts (non-void
    rows), floor 25 bps, prior until enough windows exist. Published so agents can start from the baseline."""
    from .tape import SIGMA_MIN_WINDOWS, SIGMA_PRIOR_BPS
    end = {str(w["id"]): w["end_ms"] for w in windows}
    out = {}
    for w in open_w:
        rows = [t for t in tape if t["kind"] == str(w["kind"]) and not t["void"] and t["tape_error_bps"]
                and end.get(t["window"], 1 << 62) <= w["start_ms"]]
        errs = sorted(abs(float(t["tape_error_bps"])) for t in rows)
        if len({t["window"] for t in rows}) < SIGMA_MIN_WINDOWS or not errs:
            out[w["id"]] = SIGMA_PRIOR_BPS
            continue
        n = len(errs)
        med = errs[n // 2] if n % 2 else (errs[n // 2 - 1] + errs[n // 2]) / 2
        out[w["id"]] = round(max(25.0, 1.4826 * med), 2)
    return out


def _form_json(path: Path, open_w: list[dict], sym: dict, names: dict, tape: list[dict] | None = None,
               windows: list[dict] | None = None) -> None:
    """What the form and the agents need: open windows (with the baseline's sigma), the slate with symbols and
    each token's Chainlink reference feed, the mainnet ledger and the project code."""
    import yaml
    led = {}
    lf = config.config_dir() / "ledger.yaml"
    if lf.exists():
        led = (yaml.safe_load(lf.read_text(encoding="utf-8")) or {}).get("base") or {}
    feeds = {}
    for fd in yaml.safe_load((config.config_dir() / "feeds.yaml").read_text(encoding="utf-8"))["feeds"]:
        if fd.get("token") and fd.get("kind") == "24/5":
            feeds[fd["token"].lower()] = {"proxy": fd["proxy"], "decimals": int(fd.get("decimals", 8))}
    sig = _open_sigma(open_w, tape or [], windows or [])
    slate = sorted({t for w in open_w for t in w.get("slate", [])})
    doc = {"windows": [{**{k: w[k] for k in ("id", "label", "cutoff_ms", "cutoff_et")}, "sigma_bps": sig.get(w["id"])}
                       for w in open_w],
           "slate": [{"address": t, "symbol": sym.get(t), "name": names.get(t),
                      "reference_feed": feeds.get(t.lower())} for t in slate],
           "ledger": {"address": led["address"], "chain_id": 8453} if led.get("address") else None,
           "builder_codes": [led["builder_code"]] if led.get("builder_code") else [],
           # the CDP paymaster URL for sponsored gas (smart wallets only); from the PAYMASTER_URL secret at build
           # time, never stored in the repository; capped and allowlisted to commit() on the CDP side
           "paymaster_url": os.environ.get("PAYMASTER_URL") or None}
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _board_table(rows: list[dict]) -> str:
    if not rows:
        return ('<div class="empty"><strong>No outside forecaster yet. Be the first to beat the rivals.</strong>'
                'Every forecaster appears here once a window it predicted has been scored, every weekday evening and '
                'every Sunday night. <a href="agents.html">Plug in your agent</a> or '
                '<a href="commit.html">predict by hand</a>.</div>')
    out = []
    for f in rows:
        c = f["committer"].lower()
        tag = house_tag(f.get("house_role"))
        rank = esc(f["rank"]) if f.get("rank") else '<span class="tag" title="ranked once it has enough scored windows">new</span>'
        out.append([rank, f'<a class="mono" href="f/{c}.html">{esc(short(c))}</a>{tag}',
                    esc(f["windows_scored"]), fnum(f["brier"], 4), fnum(f["skill_vs_dex"], 3, sign=True),
                    fnum(f["skill_vs_50"], 3, sign=True), fnum(f["edge_lcb"], 4, sign=True)])
    return table([("rank", True), ("forecaster", False), ("windows", True), ("score", True), ("vs Weekend DEX", True),
                  ("vs coin flip", True), ("edge, luck discounted", True)], out)


GOAL = (25, "Dec 1")   # the public goal for outside forecasters (house wallets never count)


def _counter(usage: dict, small: bool = False) -> str:
    """Outside forecasters on the record (wallets with at least one record, house wallets excluded), against
    the public goal. Shown as measured, zero included."""
    n = int(usage.get("external_wallets") or 0)
    recs = int(usage.get("external_records") or 0)
    if small:
        return (f'<p class="counter-small"><b>{n}</b> outside forecaster{"" if n == 1 else "s"} on the record so far. '
                f'Goal: {GOAL[0]} by {GOAL[1]}.</p>')
    pct = min(100.0, n / GOAL[0] * 100)
    return (f'<div class="counter"><div><div class="big">{n}<small> / {GOAL[0]}</small></div>'
            f'<div class="k">outside forecasters on the record, goal by {GOAL[1]}. {recs} outside '
            f'prediction{"" if recs == 1 else "s"} so far; house wallets never count.</div></div>'
            f'<div class="meter" role="img" aria-label="{n} of {GOAL[0]}"><i style="width:{pct:.1f}%"></i></div></div>')


def _rivals_block(b: dict) -> str:
    """The three house rivals on top of the board, so it is never empty. The Weekend DEX record is computed for
    every resolved window since Aug 24 as if it had been on the record, and says so."""
    c, d = b.get("closed") or {}, b.get("daily") or {}
    if not c.get("pairs"):
        return ""
    hit = f' It had the direction right {c["direction_hit_rate"] * 100:.0f}% of the time.' if c.get("direction_hit_rate") is not None else ""
    day = (f' On weekday closes it scores {d["brier"]:.3f}, {"worse" if d["skill_vs_50"] < 0 else "better"} than a coin flip.'
           if d.get("pairs") else "")
    return ('<h2>The rivals to beat</h2><div class="grid rivals">'
            f'<div class="card stat hot"><div class="v">{c["brier"]:.3f}</div><div class="k"><b>Weekend DEX</b>: the '
            f'last-hour weekend DEX price, read as odds. Computed over {c["windows"]} weekends and holidays since Aug 24, '
            f'as if it had been on the record.{hit}{day}</div></div>'
            '<div class="card stat"><div class="v">0.250</div><div class="k"><b>Coin Flip</b>: says 50% on every stock, '
            'every window. Any forecaster with real skill scores below it.</div></div>'
            '<div class="card stat"><div class="v">0.250</div><div class="k"><b>Frozen Price</b>: says nothing moves. '
            'Its odds score like a coin flip; it is the rival for the size of the move.</div></div></div>')


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
    return ('<h2>Rival details: the Weekend DEX since Aug 24</h2><p>Computed for every resolved window from the data, '
            'as if it had been on the record (it was not: house records start when the contract is deployed). '
            'This is the forecaster to beat.</p>'
            + table([("windows", False), ("count", True), ("stock-windows", True), ("score", True),
                     ("vs coin flip", True), ("direction right", True), ("no usable DEX price", True)], rows))


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
        # a void row's DEX-derived values are kept in tape.csv as measured, but never shown as if usable
        dx = (lambda k: None) if t["void"] else (lambda k, t=t: t[k])
        out.append([esc(sym.get(t["token"], short(t["token"]))), fnum(t["frozen_ref"], 2), fnum(dx("twap_last_hour"), 2),
                    fnum(t["reopen_ref"], 2), fnum(dx("gap_bps"), 0, sign=True), fnum(t["reopen_bps"], 0, sign=True),
                    fnum(dx("tape_error_bps"), 0, sign=True), fnum(dx("max_abs_gap_bps"), 0), esc(t["swaps_span"]),
                    usd(t["volume_span_usd"]), fnum(t["alt_247_ref"], 2), esc(t["void"] or "")])
    return table([("token", False), ("frozen ref", True), ("DEX last hour", True), ("reopen ref", True),
                  ("gap bps", True), ("reopen bps", True), ("error bps", True), ("max gap bps", True),
                  ("swaps", True), ("volume", True), ("24/7 feed", True), ("void", False)], out)


def _scatter(rows: list[dict], big: bool = False) -> str:
    """Reopen move against the last-hour gap. Axes are clipped at the 95th percentile of |value| so the
    bulk is legible; points beyond sit on the edge and the caption says how many."""
    pts = [(float(t["gap_bps"]), float(t["reopen_bps"])) for t in rows if t["gap_bps"] and t["reopen_bps"] and not t["void"]]
    if len(pts) < 3:
        return ""
    mags = sorted(max(abs(x), abs(y)) for x, y in pts)
    lim = max(50.0, mags[min(len(mags) - 1, int(len(mags) * 0.95))] * 1.1)
    lim = float(int(lim / 50 + 1) * 50)
    n_out = sum(1 for x, y in pts if abs(x) > lim or abs(y) > lim)
    W, H, M = (560, 460, 44) if big else (560, 420, 44)

    def sx(x):
        return M + (max(-lim, min(lim, x)) + lim) / (2 * lim) * (W - 2 * M)

    def sy(y):
        return H - M - (max(-lim, min(lim, y)) + lim) / (2 * lim) * (H - 2 * M)
    step = lim / 2
    grid = "".join(f'<line x1="{M}" y1="{sy(v):.1f}" x2="{W - M}" y2="{sy(v):.1f}"/><line x1="{sx(v):.1f}" y1="{M}" x2="{sx(v):.1f}" y2="{H - M}"/>'
                   for v in (-lim, -step, step, lim))
    ticks = ("".join(f'<text x="{sx(v):.1f}" y="{H - M + 20}" text-anchor="middle">{v:+,.0f}</text>' for v in (-lim, lim))
             + f'<text x="{M - 8}" y="{sy(lim) + 4:.1f}" text-anchor="end">{lim:+,.0f}</text>')
    order = sorted(range(len(pts)), key=lambda i: abs(pts[i][0]) + abs(pts[i][1]))
    rank = {i: k for k, i in enumerate(order)}
    dots = "".join(f'<circle class="dot" cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="{4.2 if big else 3.6}" style="--d:{rank[i] * 9}"/>'
                   for i, (x, y) in enumerate(pts))
    return (f'<figure><svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="Reopen move against the last-hour DEX gap, in basis points">'
            f'<g class="grid">{grid}</g>'
            f'<line class="axis" x1="{M}" y1="{sy(0):.1f}" x2="{W - M}" y2="{sy(0):.1f}"/>'
            f'<line class="axis" x1="{sx(0):.1f}" y1="{M}" x2="{sx(0):.1f}" y2="{H - M}"/>'
            f'<line class="diag" x1="{sx(-lim):.1f}" y1="{sy(-lim):.1f}" x2="{sx(lim):.1f}" y2="{sy(lim):.1f}"/>{dots}{ticks}'
            f'<text x="{W / 2:.1f}" y="{H - M + 20}" text-anchor="middle">weekend gap, bps &rarr;</text>'
            f'<text x="{sx(0) + 8:.1f}" y="{M + 12}">reopen move, bps</text></svg>'
            f'<figcaption>Each dot is one token in one closed span; {len(pts)} points'
            + (f', {n_out} beyond &plusmn;{lim:,.0f} bps drawn at the edge' if n_out else "")
            + '. On the dashed line the weekend DEX price matched the reopen exactly.</figcaption></figure>')


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
    return ('<h1>Predict the reopen</h1>'
            '<p class="lede">Give each stock a probability that it reopens higher than its frozen price. One '
            'transaction sends them to a contract that holds no funds; after the window closes, Chainlink\'s price '
            'scores every prediction. Your first prediction per window is the one that counts.</p>'
            '<div class="note">This records a forecast. It does not touch any token, route anything or move any value; '
            'the transaction carries no ETH beyond gas. Your probabilities appear on the board only after the window resolves.</div>'
            '<div class="card formcard"><p><label for="window">Window</label><br><select id="window"></select></p>'
            '<div id="tokens"></div><p><button class="btn primary" id="commit">Put it on the record</button></p>'
            '<p id="status" class="muted"></p><p class="muted">Contract <span class="mono" id="ledger"></span></p></div>'
            '<h2>For agents</h2><p>Use the TypeScript client (<code>commitCalls</code>) or send '
            '<code>commit(uint32 windowId, uint16 1, bytes data)</code> yourself; the encoding is in '
            '<a href="methods.html">METHODS section 4</a>. Append your own Builder Code in the ERC-8021 suffix; it is kept.</p>'
            '<h2>House schedule</h2><p>The project\'s own forecasters commit once per window (METHODS section 7). '
            'Daily windows: null and persistence in the 12 hours before 20:00 ET, DEX-implied in the hour before. Closed spans: null and '
            'persistence after the Friday close, DEX-implied in the two hours before the cutoff (Sunday 16:00 to '
            '18:00 ET), and the coverage call within two hours of the close. All house wallets are labelled '
            'and excluded from every usage figure.</p>')
