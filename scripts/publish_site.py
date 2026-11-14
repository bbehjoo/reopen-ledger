"""Build the site from the newest export and publish it to the public repository's gh-pages branch (GitHub
Pages serves it at identity.SITE_URL).

    uv run python scripts/publish_site.py [--export data/exports/<date>] [--dry-run]

The branch holds one commit, replaced on every publish: the site is a pure function of the export, whose
history is already in the repository. The built pages pass the same gate as the public cut.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import public_cut  # noqa: E402
from callrec import config, identity, site  # noqa: E402


def newest_export() -> Path:
    d = config.data_dir() / "exports"
    return sorted(p for p in d.iterdir() if (p / "manifest.json").exists())[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    exp = Path(a.export) if a.export else newest_export()
    out = ROOT.parent / "reopen-ledger-site"
    if out.exists():
        shutil.rmtree(out)
    pages = site.build_site(exp, out)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    problems = public_cut.gate(out, files)
    print(f"{len(pages)} pages, {len(files)} files from {exp.name}")
    if problems:
        print("GATE FAILED:\n  " + "\n  ".join(problems[:40]))
        return 1
    if a.dry_run:
        return 0
    env = {**os.environ, "GIT_AUTHOR_NAME": public_cut.AUTHOR[0], "GIT_AUTHOR_EMAIL": public_cut.AUTHOR[1],
           "GIT_COMMITTER_NAME": public_cut.AUTHOR[0], "GIT_COMMITTER_EMAIL": public_cut.AUTHOR[1]}
    run = lambda *c: subprocess.run(list(c), cwd=out, check=True, env=env, capture_output=True)  # noqa: E731
    run("git", "init", "-q", "-b", "gh-pages")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", f"Site from export {exp.name}")
    run("git", "push", "-q", "--force", public_cut.PUBLIC_REMOTE, "gh-pages")
    print("published", identity.SITE_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
