"""Every number the launch video shows, read from one export (no number is typed into the video by hand).

    uv run python video/data/make_data.py [data/exports/<date>]   ->  video/src/data.json
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from callrec.tape import tape_stats  # noqa: E402

exports = sorted(p for p in (ROOT / "data" / "exports").iterdir() if p.is_dir())
E = Path(sys.argv[1]) if len(sys.argv) > 1 else exports[-1]
tape = list(csv.DictReader((E / "tape.csv").open(encoding="utf-8")))
closed = [t for t in tape if t["kind"] == "1"]
ts = tape_stats(tape)
ab = json.loads((E / "absorb.json").read_text(encoding="utf-8"))
base = json.loads((E / "baselines.json").read_text(encoding="utf-8")).get("closed", {})
tok = {t["address"]: t["symbol"] for t in json.loads((ROOT / "config" / "tokens.json").read_text(encoding="utf-8"))["tokens"]}
import yaml  # noqa: E402

led = (yaml.safe_load((ROOT / "config" / "ledger.yaml").read_text(encoding="utf-8")) or {}).get("base", {})
tot = ab["lending_totals"]["total"]
shock = sorted(({"s": tok.get(x["token"], x["token"][:8]),
                 "flow": round((x.get("liquidation_flow_usd") or {}).get("20") or 0),
                 "depth": round((x.get("absorb_5pct_below_usd") or {}).get("20") or 0)} for x in ab["tokens"]),
               key=lambda r: -r["flow"])
pts = [[round(float(t["gap_bps"]), 1), round(float(t["reopen_bps"]), 1)] for t in closed
       if t["gap_bps"] and t["reopen_bps"] and not t["void"]]
manifest = json.loads((E / "manifest.json").read_text(encoding="utf-8"))
out = {
    "export": E.name, "as_of": manifest.get("as_of_utc"), "methods_version": manifest.get("methods_version"),
    "debt_usd": tot["debt_usd"], "collateral_usd": tot["collateral_usd"], "borrowers": tot["borrowers"],
    "weekends": len({t["window"] for t in closed}), "token_weekends": ts["n"],
    "median_reopen_bps": ts["median_reopen_bps"], "median_error_bps": ts["median_error_bps"],
    "max_reopen_bps": ts["max_reopen_bps"], "direction_hit_rate": base.get("direction_hit_rate"),
    "skill_vs_50": base.get("skill_vs_50"),
    "shock20": {"flow": sum(r["flow"] for r in shock), "depth": sum(r["depth"] for r in shock),
                "over": sum(1 for r in shock if r["flow"] > r["depth"]), "n": len(shock), "tokens": shock[:6]},
    "points": pts, "ledger": led.get("address"), "builder_code": led.get("builder_code"),
}
dst = ROOT / "video" / "src" / "data.json"
dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
print(dst, E.name)
