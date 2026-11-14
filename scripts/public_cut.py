"""Cut the public repository from this one, check it, and (with --push) publish it.

    uv run python scripts/public_cut.py --out ../reopen-ledger-public [--push]

The cut is every file tracked at HEAD (`git archive`), minus the internal notes, the drafts and the workflows
that hold keys. Before anything is written to the public repository the cut must pass the gate:

  - the vocabulary scan (callrec.language) over every text file;
  - no earlier project of the author named anywhere, licence files included (tests/test_language.py);
  - no private name, e-mail or secret value from .env in any file;
  - no file larger than 50 MB (GitHub's warning size).

With --push the cut is committed to the public repository (`public_remote` below) on top of its history, by a
neutral author, with a neutral message; the first commit is an orphan, so no private history is published.
The site is pushed separately (scripts/publish_site.py).
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from callrec import identity  # noqa: E402
from callrec.language import scan  # noqa: E402


def rmtree(p: Path) -> None:
    """shutil.rmtree that also removes read-only files (git marks its objects read-only on Windows)."""
    def writable(func, path, _exc):
        os.chmod(path, 0o666)
        func(path)
    shutil.rmtree(p, onexc=writable)

EXCLUDE_FILES = {"CRITIQUE.md", "PROJECT-STATE.md", "CLAUDE.md", "docs/NAMING.md"}
EXCLUDE_DIRS = ("drafts/", ".github/workflows/")
KEEP_WORKFLOWS = {".github/workflows/tests.yml"}
TEXT = {".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".html", ".css", ".js", ".ts",
        ".mjs", ".sol", ".csv", ".svg", ".sh", ".ps1", ""}
LEGAL = {"LICENSE", "DATA-LICENSE", "OFL.txt"}
# private identifiers, spelled backwards so this file does not carry them either
PRIVATE = [w[::-1] for w in ("gnarheb", "oojheb gnarheb", "5oojhebb", "moc.liamg@5oojhebb")]
AUTHOR = ("Reopen Ledger", "reopen-ledger@users.noreply.github.com")
PUBLIC_REMOTE = os.environ.get("PUBLIC_REMOTE", "https://github.com/bbehjoo/reopen-ledger.git")   # CI: ssh + deploy key


def keep(path: str) -> bool:
    if path in EXCLUDE_FILES:
        return False
    if path in KEEP_WORKFLOWS:
        return True
    return not path.startswith(EXCLUDE_DIRS)


def export_head(out: Path) -> list[str]:
    raw = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    kept = []
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if not m.isfile() or not keep(m.name):
                continue
            dst = out / m.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(tf.extractfile(m).read())
            kept.append(m.name)
    return sorted(kept)


def secrets() -> list[str]:
    try:
        from dotenv import dotenv_values
    except ImportError:
        return []
    vals = [v for v in dotenv_values(ROOT / ".env").values() if v]
    vals += [os.environ[k] for k in ("HOUSE_MNEMONIC", "EXPORT_SIGNING_KEY") if os.environ.get(k)]   # CI
    out = []
    for v in vals:
        out.append(v)
        if " " in v:            # a mnemonic: any run of three of its words
            ws = v.split()
            out += [" ".join(ws[i:i + 3]) for i in range(len(ws) - 2)]
    return out


def gate(out: Path, files: list[str]) -> list[str]:
    import test_language
    earlier = test_language.EARLIER_PROJECT
    priv = re.compile("|".join(re.escape(w) for w in PRIVATE), re.IGNORECASE)
    sec = secrets()
    problems = []
    for rel in files:
        p = out / rel
        if p.stat().st_size > 50 * 1024 * 1024:
            problems.append(f"{rel}: larger than 50 MB")
        if Path(rel).suffix.lower() not in TEXT:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if Path(rel).name not in LEGAL:
            problems += [f"{rel}:{line}: word {w!r}" for line, w in scan(text)]
        if earlier.search(text):
            problems.append(f"{rel}: names an earlier project")
        if priv.search(text):
            problems.append(f"{rel}: private name or address")
        if any(s in text for s in sec):
            problems.append(f"{rel}: SECRET VALUE")
    return problems


def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


def push(out: Path, message: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1],
           "GIT_COMMITTER_NAME": AUTHOR[0], "GIT_COMMITTER_EMAIL": AUTHOR[1]}
    work = out.parent / (out.name + "-git")
    if work.exists():
        rmtree(work)
    r = subprocess.run(["git", "clone", "-q", PUBLIC_REMOTE, str(work)], capture_output=True, text=True)
    if r.returncode != 0:      # empty or new repository
        work.mkdir(parents=True)
        run(["git", "init", "-q", "-b", "main"], work)
        run(["git", "remote", "add", "origin", PUBLIC_REMOTE], work)
    for p in work.iterdir():
        if p.name != ".git":
            rmtree(p) if p.is_dir() else p.unlink()
    shutil.copytree(out, work, dirs_exist_ok=True)
    run(["git", "add", "-A"], work)
    if not run(["git", "status", "--porcelain"], work).strip():
        return "unchanged"
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=work, env=env, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=work, check=True)
    return run(["git", "rev-parse", "--short", "HEAD"], work).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "reopen-ledger-public"))
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--message", default="Update from the working repository")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if out.exists():
        rmtree(out)
    out.mkdir(parents=True)
    files = export_head(out)
    problems = gate(out, files)
    print(f"{len(files)} files in the cut at {out}")
    if problems:
        print("GATE FAILED:\n  " + "\n  ".join(problems[:40]))
        return 1
    print("gate passed")
    if a.push:
        print("pushed:", push(out, a.message), "to", identity.REPO_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
