"""The weekly posts, drafted from the newest export (nothing is posted from here):

    uv run python scripts/ritual.py freeze     # Friday 20:00 ET: the price lenders use stops
    uv run python scripts/ritual.py lock       # Sunday 18:00 ET: predictions close, sealed until the reopen
    uv run python scripts/ritual.py unfreeze   # after the reopen is scored: who beat the weekend market (with card)

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
    parts = [f"Unfrozen. {when}, scored against Chainlink:"]
    parts.append(f"best score {best['score']:.3f} by {best['name']}" + (f", called {best['called']} of {best['decided']}." if best["decided"] else "."))
    if dex:
        parts.append(f"Weekend DEX scored {dex['score']:.3f}; a coin flip scores 0.250.")
    parts.append(f"{len(beat)} outside forecaster{'s' if len(beat) != 1 else ''} beat the weekend market." if beat
                 else "Nobody outside beat the weekend market this time. Next weekend opens Friday 20:00 ET.")
    parts.append(f"{identity.SITE_URL}board.html")
    return " ".join(parts), f"site/build/cards/{w['id']}.png"


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
