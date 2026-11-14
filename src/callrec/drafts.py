"""Post drafts rendered from an export, so every number in a post is the published number.

`render_launch(export_dir)` and `render_weekend(export_dir, window_id)` return Markdown. Nothing is posted:
the drafts go to drafts/ for the operator (nothing is posted from here).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from . import config, identity
from .tape import tape_stats  # one definition for the site and the drafts


def _csv(p: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8")))) if p.exists() else []


def _json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _usd(v) -> str:
    if v is None:
        return "n/a"
    v = float(v)
    if abs(v) >= 1e6:
        return f"${v / 1e6:,.1f}M"
    if abs(v) >= 1e4:
        return f"${v / 1e3:,.0f}k"
    if abs(v) >= 1e3:   # one decimal below $10k: $4.6k is not rounded to $5k
        return f"${v / 1e3:,.1f}k"
    return f"${v:,.0f}"


def _sym() -> dict:
    t = json.loads((config.config_dir() / "tokens.json").read_text(encoding="utf-8"))
    return {x["address"]: x["symbol"] for x in t["tokens"]}




def render_launch(export_dir: Path) -> str:
    export_dir = Path(export_dir)
    m = _json(export_dir / "manifest.json", {})
    tape = _csv(export_dir / "tape.csv")
    ab = _json(export_dir / "absorb.json")
    st = tape_stats(tape)
    sym = _sym()
    lines = [f"# Launch post (draft, from export {export_dir.name}, data as of {m.get('as_of_utc')})", "",
             f"To post on X with the demo video, tagging @buildonbase. Site: {identity.SITE_URL} "
             "Every number below comes from the export named above.", "", "---", ""]
    t1 = ("Coinbase's tokenized stocks trade around the clock on Base. Their reference price doesn't: the "
          "Chainlink feed that lending markets read is frozen from Friday 20:00 to Sunday 20:00 ET, and on market "
          "holidays. We measured what happens in between, every weekend since Aug 24.")
    lines += ["**1/**", t1, ""]
    if st:
        lines += ["**2/**", (f"Across {st['windows']} closed spans and {st['n']} token-weekends, the reference moved a "
                             f"median {st['median_reopen_bps']:.0f} bps from the frozen value to the reopen (largest "
                             f"{st['max_reopen_bps']:.0f} bps). In the hour before the cutoff, the DEX price sat a median "
                             f"{st['median_gap_bps']:.0f} bps from the frozen value and finished {st['median_error_bps']:.0f} bps "
                             f"from the reopen value. It was closer to the reopen than the frozen value was in "
                             f"{st['dex_closer_than_frozen']} of {st['n']} cases, and it pointed the right way in "
                             f"{st['direction_agree']} of the {st['direction_n']} where both moves exceeded 10 bps."), ""]
    if ab and ab.get("lending_totals"):
        tot = ab["lending_totals"]["total"]
        coll, debt = tot["collateral_usd"], tot["debt_usd"]
        rows = ab["tokens"]
        d10 = sum((r["absorb_5pct_below_usd"] or {}).get("10") or 0 for r in rows)
        l10 = sum((r["liquidation_flow_usd"] or {}).get("10") or 0 for r in rows)
        l20 = sum((r["liquidation_flow_usd"] or {}).get("20") or 0 for r in rows)
        d20 = sum((r["absorb_5pct_below_usd"] or {}).get("20") or 0 for r in rows)
        lines += ["**3/**", (f"Lending against these tokens is small today: {_usd(debt)} of USDC borrowed against "
                             f"{_usd(coll)} of stock collateral on Aave V4 and Morpho. The numbers are the point, not the "
                             "size. They show what this market structure does once lending grows."), "",
                  "**4/**", (f"Shock each token's reference 10% lower, one token at a time, and add it up: these markets would "
                             f"liquidate {_usd(l10)} of collateral at the reopen, and the token pools hold {_usd(d10)} in the "
                             f"5% below the shocked prices. At 20%: {_usd(l20)} against {_usd(d20)}. That uses the oracle each "
                             "market reads and each protocol's own liquidation rules. A joint move would liquidate more, "
                             "since many borrowers post several stocks. Onchain absorption only."), ""]
    lines += ["**5/**", ("Now the open question: can anyone call the reopen better than the weekend market does? Put a "
                         "call on the record: one transaction, a probability per token, no funds, no trading. It's scored "
                         "against the Chainlink feed after the window closes. Agents can do it with one function and keep "
                         "their own Builder Code."), "",
              "**6/**", ("Every number is replayable from the published chain logs. Each daily export is signed, and its "
                         "hash goes on chain. Measurements, not verdicts. Methods, data and the board: " + identity.SITE_URL + ""), "",
              "[demo video]", ""]
    return "\n".join(lines)


def render_weekend(export_dir: Path, window_id: str | None = None) -> str:
    export_dir = Path(export_dir)
    tape = [r for r in _csv(export_dir / "tape.csv") if r["kind"] == "1"]
    windows = {str(w["id"]): w for w in _json(export_dir / "windows.json", {"windows": []})["windows"]}
    if window_id is None:
        done = sorted({r["window"] for r in tape if r["reopen_bps"]})
        window_id = done[-1] if done else None
    if window_id is None:
        return "# Weekend Report\n\nNo closed window has resolved yet.\n"
    rows = sorted([r for r in tape if r["window"] == window_id], key=lambda r: r["token"])
    sym = _sym()
    w = windows.get(window_id, {})
    board = _json(export_dir / "leaderboard.json", {"forecasters": []})["forecasters"]
    out = [f"# Weekend Report: {w.get('label', window_id)}", "",
           f"Draft from export {export_dir.name}. Frozen at {w.get('start_et')}; the reopen value is the reference at "
           f"{w.get('end_et')}, one hour after the 20:00 reopen. 'DEX, last hour' is the hour before the cutoff, two "
           "hours before the reopen. Rows marked void are shown but not used in any score.", "",
           "| token | frozen | DEX, last hour | reopen | gap bps | reopen bps | error bps | void |",
           "|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        def f(k, nd=2):
            return f"{float(r[k]):,.{nd}f}" if r[k] else "n/a"
        out.append(f"| {sym.get(r['token'], r['token'][:10])} | {f('frozen_ref')} | {f('twap_last_hour')} | "
                   f"{f('reopen_ref')} | {f('gap_bps', 0)} | {f('reopen_bps', 0)} | {f('tape_error_bps', 0)} | {r['void'] or ''} |")
    st = tape_stats(rows)   # non-void rows only
    if st:
        out += ["", (f"Median distance from the last-hour DEX price to the reopen value: {st['median_error_bps']:.0f} bps; "
                     f"median move of the reference across the span: {st['median_reopen_bps']:.0f} bps.")]
    out += ["", "## The board", "", "| rank | forecaster | windows | skill vs DEX | skill vs 50% |", "|---:|---|---:|---:|---:|"]
    for b in board[:8]:
        lab = f"house: {b['house_role']}" if b.get("house_role") else b["committer"][:10]
        sk = f"{b['skill_vs_dex']:+.3f}" if b.get("skill_vs_dex") is not None else "n/a"
        s5 = f"{b['skill_vs_50']:+.3f}" if b.get("skill_vs_50") is not None else "n/a"
        out.append(f"| {b.get('rank') or ''} | {lab} | {b['windows_scored']} | {sk} | {s5} |")
    out += ["", "With a few dozen windows, skill and luck cannot yet be told apart. Measurements, not verdicts.", ""]
    return "\n".join(out)
