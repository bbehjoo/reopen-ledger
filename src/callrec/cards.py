"""Shareable result cards (PNG, 1200x675) for the Sunday reveal, built from one export.

* window card: who beat the weekend market in one resolved window (the board for that window);
* forecaster card: one forecaster's result in its latest scored window, for its page and its share link.

Everything shown comes from the export: forecasters/<wallet>.json pairs (p, o, brier, baseline_brier) and
leaderboard.json (house roles). "Called" counts pairs where p is not 0.5 and points the way the outcome
went; the score is the mean Brier (lower is better); the Weekend DEX is the DEX-implied baseline on the same
pairs; Coin Flip is 0.25 by construction.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config, identity

W, H = 1200, 675
BG = (11, 12, 14)
FG = (238, 240, 242)
MUTED = (146, 152, 162)
DIM = (99, 105, 115)
LINE = (38, 40, 45)
ACCENT = (255, 106, 43)
POS = (87, 211, 154)
HOUSE_NAMES = {"null": "Coin Flip", "persistence": "Frozen Price", "dex_implied": "Weekend DEX"}
FONTS = config.ROOT / "assets" / "fonts"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _short(a: str) -> str:
    return a[:6] + "..." + a[-4:]


def _name(committer: str, role: str | None) -> str:
    return HOUSE_NAMES.get(role or "", _short(committer)) if role else _short(committer)


def _when(label: str) -> str:
    """'closed 2026-11-13 (Fri) -> 2026-11-15 (Sun)' -> 'Weekend of Nov 13'; daily -> 'Session of Nov 13'."""
    import datetime as dt
    parts = label.split()
    try:
        d = dt.date.fromisoformat(parts[1])
    except (IndexError, ValueError):
        return label
    month = d.strftime("%b")
    return (f"Weekend of {month} {d.day}" if parts[0] == "closed" and d.weekday() == 4
            else f"{'Holiday close' if parts[0] == 'closed' else 'Session'} of {month} {d.day}")


def window_results(export_dir: Path, window_id: int) -> list[dict]:
    """Per forecaster scored in the window: name, called/decided, score, DEX score, streak; best score first."""
    export_dir = Path(export_dir)
    board = json.loads((export_dir / "leaderboard.json").read_text(encoding="utf-8"))
    out = []
    for f in board.get("forecasters", []):
        c = f["committer"].lower()
        p = export_dir / "forecasters" / f"{c}.json"
        if not p.exists():
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        wins = sorted(doc.get("windows", []), key=lambda w: w["window"])
        mine = next((w for w in wins if int(w["window"]) == int(window_id)), None)
        if not mine or not mine.get("pairs"):
            continue
        pairs = mine["pairs"]
        decided = [x for x in pairs if abs(float(x["p"]) - 0.5) > 1e-9]
        called = sum(1 for x in decided if (float(x["p"]) > 0.5) == (int(x["o"]) == 1))
        score = sum(float(x["brier"]) for x in pairs) / len(pairs)
        dex = sum(float(x["baseline_brier"]) for x in pairs) / len(pairs)
        streak = 0
        for w in reversed([w for w in wins if int(w["window"]) <= int(window_id)]):
            ps = w.get("pairs") or []
            if ps and sum(float(x["brier"]) for x in ps) < sum(float(x["baseline_brier"]) for x in ps):
                streak += 1
            else:
                break
        out.append({"committer": c, "role": f.get("house_role"), "name": _name(c, f.get("house_role")),
                    "called": called, "decided": len(decided), "pairs": len(pairs), "score": score, "dex": dex,
                    "streak": streak})
    # When the Weekend DEX house forecaster scored this window, everyone is compared with its actual score (what
    # the card shows for it), not with the end-of-window baseline it was committed ahead of.
    dex = next((r for r in out if r["role"] == "dex_implied"), None)
    if dex:
        for r in out:
            r["dex"] = dex["score"]
    return sorted(out, key=lambda r: (r["score"], r["name"]))


def latest_scored_window(export_dir: Path, kinds: tuple[int, ...] = (1, 2)) -> dict | None:
    """The most recent resolved window with at least one scored forecaster (closed windows first)."""
    export_dir = Path(export_dir)
    windows = json.loads((export_dir / "windows.json").read_text(encoding="utf-8")).get("windows", [])
    for kind in kinds:
        for w in sorted((w for w in windows if w.get("kind") == kind), key=lambda w: -int(w["end_ms"])):
            if window_results(export_dir, w["id"]):
                return w
    return None


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 520, -300, W + 260, 420), fill=ACCENT + (95,))
    img.paste(glow.filter(ImageFilter.GaussianBlur(140)), (0, 0), glow.filter(ImageFilter.GaussianBlur(140)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((64, 52, 104, 92), radius=11, fill=ACCENT)
    d.line([(73, 77), (86, 77), (95, 65)], fill=(22, 10, 4), width=4, joint="curve")
    d.ellipse((92, 62, 99, 69), fill=(22, 10, 4))
    d.text((118, 56), identity.NAME, font=_font("Geist-SemiBold.ttf", 28), fill=FG)
    return img, d


def render_window_card(window: dict, results: list[dict], path: Path) -> Path:
    img, d = _canvas()
    d.text((64, 128), f"UNFREEZE  /  {_when(window['label']).upper()}", font=_font("GeistMono-SemiBold.ttf", 22), fill=ACCENT)
    title = "Who beat the weekend market?" if window.get("kind") == 1 else "Who called the session?"
    d.text((64, 164), title, font=_font("Geist-Bold.ttf", 60), fill=FG)
    cols = (64, 560, 760, 960)
    y = 268
    for x, t in zip(cols, ("forecaster", "called", "score", "vs Weekend DEX"), strict=True):
        d.text((x, y), t, font=_font("GeistMono-Medium.ttf", 20), fill=DIM)
    y += 40
    for r in results[:6]:
        d.line([(64, y - 10), (W - 64, y - 10)], fill=LINE, width=1)
        house = r["role"] is not None
        d.text((cols[0], y), r["name"], font=_font("Geist-SemiBold.ttf", 30), fill=MUTED if house else FG)
        d.text((cols[1], y), f"{r['called']} of {r['decided']}" if r["decided"] else "none", font=_font("GeistMono-Medium.ttf", 28), fill=FG)
        d.text((cols[2], y), f"{r['score']:.3f}", font=_font("GeistMono-Medium.ttf", 28), fill=FG)
        diff = r["dex"] - r["score"]
        d.text((cols[3], y), f"{diff:+.3f}" if r["role"] != "dex_implied" else "baseline",
               font=_font("GeistMono-SemiBold.ttf", 28), fill=POS if diff > 0 and r["role"] != "dex_implied" else MUTED)
        y += 52
    d.text((64, H - 70), "Score: Brier, lower is better. Coin Flip scores 0.250. Scored against Chainlink at the reopen.",
           font=_font("Geist-Medium.ttf", 20), fill=MUTED)
    d.text((64, H - 42), identity.SITE_URL.replace("https://", ""), font=_font("GeistMono-Medium.ttf", 20), fill=DIM)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    return path


def render_forecaster_card(window: dict, r: dict, path: Path) -> Path:
    img, d = _canvas()
    d.text((64, 128), f"{_when(window['label']).upper()}  /  {r['name']}", font=_font("GeistMono-SemiBold.ttf", 22), fill=ACCENT)
    head = f"Called {r['called']} of {r['decided']}" if r["decided"] else "On the record"
    d.text((64, 166), head, font=_font("Geist-Bold.ttf", 112), fill=FG)
    beat = r["score"] < r["dex"]
    d.text((64, 318), "Beat the weekend market." if beat else "The weekend market won this one.",
           font=_font("Geist-Bold.ttf", 52), fill=ACCENT if beat else MUTED)
    stats = [("score", f"{r['score']:.3f}"), ("Weekend DEX", f"{r['dex']:.3f}"), ("Coin Flip", "0.250")]
    if r["streak"] > 1:
        stats.append(("streak", f"{r['streak']} in a row"))
    x = 64
    for k, v in stats:
        d.text((x, 430), v, font=_font("GeistMono-SemiBold.ttf", 40), fill=FG)
        d.text((x, 482), k, font=_font("Geist-Medium.ttf", 22), fill=MUTED)
        x += 270
    d.text((64, H - 70), "Predictions committed on Base before the cutoff, scored against Chainlink at the reopen.",
           font=_font("Geist-Medium.ttf", 20), fill=MUTED)
    d.text((64, H - 42), identity.SITE_URL.replace("https://", ""), font=_font("GeistMono-Medium.ttf", 20), fill=DIM)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    return path


def build_cards(export_dir: Path, out: Path) -> dict:
    """Window cards for the latest scored weekend (or holiday) and the latest scored weekday session, and one
    card per forecaster for its most recent of those. Returns what it made; the newest window comes first."""
    shown = [w for w in (latest_scored_window(export_dir, (1,)), latest_scored_window(export_dir, (2,))) if w]
    if not shown:
        return {}
    shown.sort(key=lambda w: -int(w["end_ms"]))
    made = {"windows": [], "forecaster_cards": {}, "latest": {}}
    for w in shown:
        res = window_results(export_dir, w["id"])
        rel = f"cards/{w['id']}.png"
        render_window_card(w, res, Path(out) / rel)
        made["windows"].append({"window": w, "card": rel, "results": res})
        for r in res:
            if r["committer"] in made["forecaster_cards"]:
                continue   # already carded from a more recent window
            frel = f"cards/f/{r['committer']}.png"
            render_forecaster_card(w, r, Path(out) / frel)
            made["forecaster_cards"][r["committer"]] = frel
            made["latest"][r["committer"]] = r
    made["window"], made["window_card"] = shown[0], made["windows"][0]["card"]
    return made
