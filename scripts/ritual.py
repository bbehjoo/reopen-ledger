"""The weekly posts, drafted from the newest export (nothing is posted from here):

    uv run python scripts/ritual.py freeze     # Friday 20:00 ET: the price lenders use stops
    uv run python scripts/ritual.py lock       # Sunday 18:00 ET: predictions close, sealed until the reopen
    uv run python scripts/ritual.py unfreeze   # after the reopen is scored: who beat the weekend market (with card)
    uv run python scripts/ritual.py live       # during the freeze: what would be liquidated at today's DEX prices

Each writes drafts/<date>-<kind>.md. The unfreeze draft names the card image to attach (built into the site
by callrec.cards under site/build/cards/).
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from callrec import cards, config, identity  # noqa: E402

HOUSE = {"null", "persistence", "dex_implied", "coverage", "anchor"}


def newest_export() -> Path:
    return sorted(p for p in (config.data_dir() / "exports").iterdir() if p.is_dir())[-1]


def _json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def freeze(e: Path) -> str:
    ab = _json(e / "absorb.json", {}) or {}
    debt = ((ab.get("lending_totals") or {}).get("total") or {}).get("debt_usd")
    base = (_json(e / "baselines.json", {}) or {}).get("closed") or {}
    lines = ["Frozen. Stock tokens trade all weekend on Base, but the price lenders use stands still until "
             "Sun 20:00 ET."]
    if debt:
        lines.append(f"${debt / 1e6:.1f}M of loans wait on where it lands.")
    if base.get("skill_vs_50") is not None:
        lines.append(f"The weekend DEX price beats a coin flip by {base['skill_vs_50']:+.3f}. Can your agent do better?")
    lines.append(f"Predictions close Sun 18:00 ET. {identity.SITE_URL}")
    return " ".join(lines)


def lock(e: Path) -> str:
    open_w = (_json(e / "open.json", {"windows": []}) or {}).get("windows", [])
    w = next((w for w in open_w if w.get("kind") == 1), None)
    import yaml
    house = {w["address"].lower() for w in
             yaml.safe_load((config.config_dir() / "house.yaml").read_text(encoding="utf-8"))["wallets"]}
    committed = [c.lower() for c in (w or {}).get("committed", [])]
    outside = len([c for c in committed if c not in house])
    who = (f"{outside} wallet{'s' if outside != 1 else ''} and our three rivals (Coin Flip, Frozen Price, Weekend DEX)"
           if outside else "Our three rivals (Coin Flip, Frozen Price, Weekend DEX)")
    return (f"Locked. {who} are on the record for this weekend. Every prediction stays sealed until the price "
            f"lenders use comes back at 20:00 ET. Then Chainlink scores them all. {identity.SITE_URL}board.html")


def unfreeze(e: Path) -> tuple[str, str | None]:
    w = cards.latest_scored_window(e)
    if not w:
        return "No scored window in this export yet; run again after the next export.", None
    res = cards.window_results(e, w["id"])
    when = cards._when(w["label"])
    dex = next((r for r in res if r["role"] == "dex_implied"), None)
    best = res[0]
    beat = [r for r in res if r["role"] is None and dex and r["score"] < dex["score"]]
    parts = [f"Unfrozen. {when}, scored by Chainlink:"]
    if dex:
        parts.append(f"the weekend market called {dex['called']} of {dex['decided']} and scored {dex['score']:.3f} "
                     "(a coin flip scores 0.250, lower is better).")
    if best is not dex:
        parts.append(f"Best score: {best['name']}, {best['score']:.3f}.")
    parts.append(f"{len(beat)} outside forecaster{'s' if len(beat) != 1 else ''} beat it." if beat
                 else "Nobody outside beat it this time. Can your agent? Next weekend opens Friday 20:00 ET.")
    parts.append(f"{identity.SITE_URL}board.html")
    return " ".join(parts), f"{identity.SITE_URL}cards/{w['id']}.png"


def _post(url: str, body=None):
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "reopen-ledger", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def live(e: Path) -> str:
    """The Live page's reading, for a post: liquidation flow against depth if each stock reopened at its DEX
    price now (positions and depth from the export's snapshot, interpolated between shocks)."""
    import yaml
    ab = _json(e / "absorb.json", {}) or {}
    toks = ab.get("tokens") or []
    if not toks:
        return "No lending snapshot in this export."
    feeds = {f["token"].lower(): f for f in yaml.safe_load((config.config_dir() / "feeds.yaml").read_text(encoding="utf-8"))["feeds"]
             if f.get("token") and f.get("kind") == "24/5"}
    sym = {t["address"].lower(): t["symbol"] for t in json.loads((config.config_dir() / "tokens.json").read_text(encoding="utf-8"))["tokens"]}
    addrs = [t["token"].lower() for t in toks]
    best: dict[str, tuple[float, float]] = {}
    for p in _post("https://api.dexscreener.com/tokens/v1/base/" + ",".join(addrs)) or []:
        a = ((p.get("baseToken") or {}).get("address") or "").lower()
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        if a and p.get("priceUsd") and liq > best.get(a, (0.0, -1.0))[1]:
            best[a] = (float(p["priceUsd"]), liq)

    def lerp(pts, x):
        if x <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pts[-1][1]

    flow = depth = 0.0
    over, gaps = [], []
    for t in toks:
        a = t["token"].lower()
        fd = feeds.get(a)
        if not fd or a not in best:
            continue
        res = _post("https://mainnet.base.org", {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                                 "params": [{"to": fd["proxy"], "data": "0xfeaf968c"}, "latest"]})["result"]
        ref = int(res[66:130], 16) / 10 ** int(fd.get("decimals", 8))
        price = best[a][0]
        if not ref or abs(price / ref - 1) > 0.30:
            continue
        gap = (price / ref - 1) * 100
        gaps.append(gap)
        s = max(0.0, -gap)
        fl, dp = t.get("liquidation_flow_usd") or {}, t.get("absorb_5pct_below_usd") or {}
        f = lerp([(0, 0), (5, fl.get("5") or 0), (10, fl.get("10") or 0), (20, fl.get("20") or 0)], s) if s else 0.0
        d = lerp([(5, dp.get("5") or 0), (10, dp.get("10") or 0), (20, dp.get("20") or 0)], max(s, 5))
        flow, depth = flow + f, depth + d
        if f > d and f > 0:
            over.append(sym.get(a, a[:8]))
    money = (lambda v: f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.0f}k" if v >= 1e3 else f"${v:.0f}")  # noqa: E731
    url = f"{identity.SITE_URL}live.html"
    if over:
        return (f"Right now, if the frozen price reopened at the weekend DEX price, {money(flow)} of collateral on Base "
                f"would be liquidated into {money(depth)} of pool depth. {len(over)} stock{'s' if len(over) != 1 else ''} "
                f"({', '.join(over)}) would see more flow than their pools hold. Live: {url}")
    lo, hi = (min(gaps), max(gaps)) if gaps else (0, 0)
    return (f"Weekend check: the DEX prices of {len(gaps)} tokenized stocks sit between {lo:+.2f}% and {hi:+.2f}% "
            f"of their frozen price. At those prices nothing would be liquidated at the reopen. Live: {url}")


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    e = newest_export()
    card = None
    if kind == "freeze":
        text = freeze(e)
    elif kind == "lock":
        text = lock(e)
    elif kind == "unfreeze":
        text, card = unfreeze(e)
    elif kind == "live":
        text = live(e)
    else:
        print(__doc__)
        return 2
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    out = ROOT / "drafts" / f"{date}-{kind}.md"
    body = (f"# {kind.capitalize()} post (draft from export {e.name})\n\nFor the project account on X and Farcaster. "
            "Not posted.\n\n---\n\n" + text + "\n" + (f"\nAttach: `{card}`\n" if card else ""))
    out.write_text(body, encoding="utf-8", newline="\n")
    print(out)
    print(text, f"({len(text) - len(identity.SITE_URL) + 23 if identity.SITE_URL in text else len(text)} characters as X counts, link = 23)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
