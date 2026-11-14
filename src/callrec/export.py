"""Exports: data/exports/<YYYY-MM-DD>/ with every built file, a signed manifest, and replay.

The manifest records the methods version, the git commit, as_of, the SHA-256 of every input (raw files and
config files) and of every output, and is signed (signing.py). Two fields are volatile: `generated_at` and
`signature`. `replay` rebuilds the outputs from the recorded as_of with the current checkout and compares
every output file byte for byte; the inputs must hash to what the manifest records.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import METHODS_VERSION, config, signing
from .build import build, jbytes

VOLATILE = ("generated_at", "signature")
MANIFEST_SCHEMA = "callrec-export/v2"   # v2 (2026-11-10): .gz inputs are hashed uncompressed


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_commit() -> tuple[str, bool]:
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src", "config", "METHODS.md"], cwd=config.ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip())
        return c, dirty
    except Exception:
        return "unknown", True


def input_hashes() -> dict[str, str]:
    """SHA-256 of every input; for a .gz day file, of its uncompressed content (manifest schema v2)."""
    from . import store
    out = {}
    root = config.data_dir() / "raw"
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out["data/raw/" + p.relative_to(root).as_posix()] = sha256(store.content(p))
    for p in sorted(config.config_dir().glob("*")):
        if p.is_file():
            out["config/" + p.name] = sha256(p.read_bytes())
    m = config.ROOT / "METHODS.md"
    out["METHODS.md"] = sha256(m.read_bytes())
    return out


class ExportError(RuntimeError):
    pass


def data_coverage() -> dict[str, int]:
    """For every raw stream with a cursor: the time (ms) of the last block it has been read to. Rows at or
    before that time are complete; later ones may still arrive."""
    from . import store
    from .chain import schedule
    out = {}
    root = config.data_dir() / "raw"
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        cur = store.cursor(d.name)
        if cur is not None:
            out[d.name] = schedule().ts_ms(int(cur["to_block"]))
    return out


MAX_LAG_MS = 2 * 3_600_000


def effective_as_of(requested_ms: int, max_lag_ms: int = MAX_LAG_MS) -> tuple[int, dict[str, int]]:
    """An export is as of the earliest time every stream has been read to (whole minutes), never later: an
    as_of past the data would let a later replay, with more rows read, give different files (found
    2026-11-10: the 2026-11-09 export said 02:05 with swaps read to 01:59). Raises when a stream lags the
    requested time by more than max_lag_ms, so a failed ingest stops the export instead of dating it back."""
    cov = data_coverage()
    eff = min([requested_ms] + list(cov.values()))
    eff -= eff % 60_000
    if requested_ms - eff > max_lag_ms:
        lag = min(cov, key=cov.get)
        raise ExportError(f"stream {lag} is read only to {datetime.fromtimestamp(cov[lag] / 1000, UTC):%Y-%m-%d %H:%M} "
                          f"UTC, more than {max_lag_ms // 60_000} min before the requested as_of; ingest it first")
    return eff, cov


def export_run(as_of_ms: int, out_dir: Path | None = None, sign: bool = True, max_lag_ms: int = MAX_LAG_MS) -> dict:
    requested_ms = as_of_ms
    as_of_ms, coverage = effective_as_of(as_of_ms, max_lag_ms)
    as_of = datetime.fromtimestamp(as_of_ms / 1000, UTC)
    out_dir = Path(out_dir or config.data_dir() / "exports" / as_of.strftime("%Y-%m-%d"))
    inputs = input_hashes()   # before the build: the hashes describe what the build read (no concurrent ingest)
    files = build(as_of_ms)
    key = signing.key_from_env() if sign else None
    if key is not None:   # per-token feed records carry their own signature (METHODS.md section 9)
        for rel in [k for k in files if k.startswith("feed/")]:
            files[rel] = jbytes(signing.sign_document(json.loads(files[rel]), key))
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    commit, dirty = git_commit()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "methods_version": METHODS_VERSION,
        "as_of_ms": as_of_ms,
        "as_of_utc": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of_requested_ms": requested_ms,
        "data_read_to_ms": coverage,
        "git_commit": commit,
        "dirty": dirty,
        "inputs": inputs,
        "files": {rel: sha256(data) for rel, data in sorted(files.items())},
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if key is not None:
        manifest = signing.sign_document(manifest, key)
    raw = jbytes(manifest)
    (out_dir / "manifest.json").write_bytes(raw)
    return {"dir": str(out_dir), "files": len(files), "manifest_sha256": sha256(raw), "signed": key is not None,
            "dirty": dirty, "as_of_utc": manifest["as_of_utc"]}


def replay(export_dir: Path) -> dict:
    export_dir = Path(export_dir)
    m = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    now_inputs = input_hashes()
    input_diffs = sorted(k for k in set(m["inputs"]) | set(now_inputs)
                         if k.startswith("data/raw/") and m["inputs"].get(k) != now_inputs.get(k)
                         and k in m["inputs"])
    files = build(int(m["as_of_ms"]))
    diffs = []
    for rel, want in sorted(m["files"].items()):
        got = sha256(files[rel]) if rel in files else None
        if got != want and rel.startswith("feed/") and rel in files and (export_dir / rel).exists():
            # signed per-token records: compare without the signature (a replay may run without the key)
            a = json.loads((export_dir / rel).read_text(encoding="utf-8"))
            b = json.loads(files[rel])
            a.pop("signature", None)
            b.pop("signature", None)
            if a == b and sha256((export_dir / rel).read_bytes()) == want:
                continue
        if got != want:
            diffs.append({"file": rel, "want": want, "got": got})
    for rel in sorted(set(files) - set(m["files"])):
        diffs.append({"file": rel, "reason": "only in replay"})
    sig_ok = None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        k = json.loads((config.ROOT / "keys" / "export-key.json").read_text(encoding="utf-8"))
        pk = Ed25519PublicKey.from_public_bytes(signing.unb64u(k["public_key"]))
        sig_ok = signing.verify_document(m, pk) if "signature" in m else None
    except Exception:
        sig_ok = False
    # raw day files keep growing after an export (rows after as_of are appended), so a changed input hash is
    # reported, not counted: the build reads only rows at or before as_of, and the outputs are what is compared
    return {"identical": not diffs, "files_checked": len(m["files"]), "differences": diffs,
            "changed_inputs_informational": input_diffs, "signature_valid": sig_ok,
            "methods_version": m["methods_version"],
            "replayed_with_methods": METHODS_VERSION}
