"""Every number the 20-second cut shows, read from one export, plus the result card it shows.

    uv run python video/data/make_short.py [data/exports/<date>] [window_id]
        ->  video/src/short.json and video/public/card.png

The window defaults to the newest scored weekend. The Weekend DEX house forecaster's record in that window is
the commit shown on screen (its transaction, block and Builder Code come from data/house-log/).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from callrec import cards  # noqa: E402

exports = sorted(p for p in (ROOT / "data" / "exports").iterdir() if p.is_dir())
E = Path(sys.argv[1]) if len(sys.argv) > 1 else exports[-1]
win = (next(w for w in json.loads((E / "windows.json").read_text(encoding="utf-8"))["windows"]
            if int(w["id"]) == int(sys.argv[2])) if len(sys.argv) > 2 else cards.latest_scored_window(E, (1,)))
res = cards.window_results(E, win["id"])
dex = next(r for r in res if r["role"] == "dex_implied")
doc = json.loads((E / "forecasters" / f"{dex['committer']}.json").read_text(encoding="utf-8"))
mine = next(w for w in doc["windows"] if int(w["window"]) == int(win["id"]))
tok = {t["address"].lower(): t["symbol"] for t in
       json.loads((ROOT / "config" / "tokens.json").read_text(encoding="utf-8"))["tokens"]}
log = {}
for f in sorted((ROOT / "data" / "house-log").glob("*.jsonl")):
    for line in f.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("tx") == mine["record_tx"]:
            log = r
calls = sorted(({"s": tok.get(x["token"].lower(), x["token"][:8]), "p": round(float(x["p"]), 2), "o": int(x["o"])}
                for x in mine["pairs"]), key=lambda c: c["s"])
out = {
    "export": E.name, "window": win["id"], "when": cards._when(win["label"]),
    "tx": mine["record_tx"], "block": log.get("block"), "builder_code": (log.get("attribution") or [None])[0],
    "calls": calls, "called": dex["called"], "decided": dex["decided"],
    "scores": [{"name": r["name"], "score": round(r["score"], 3)} for r in res],
}
(ROOT / "video" / "src" / "short.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
cards.render_window_card(win, res, ROOT / "video" / "public" / "card.png")
print(json.dumps({k: out[k] for k in ("window", "when", "called", "decided", "scores", "block")}))
