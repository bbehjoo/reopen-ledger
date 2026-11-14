"""Measurements, not verdicts, and no trade-direction or advice words (CLAUDE.md, METHODS.md §1):
the forbidden words of callrec.language never appear in a tracked file or a commit message.

Also: no earlier project of the author is named outside the internal notes, licence files included (its
words are spelled backwards here, as in callrec.language)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from callrec.language import scan

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".jsonl", ".html", ".css", ".js", ".ts",
    ".mjs", ".sol", ".csv", ".svg", ".sh", ".ps1", "",
}
LEGAL_TEXTS = {"LICENSE", "DATA-LICENSE", "OFL.txt"}  # verbatim license texts, not ours to edit (OFL.txt: the
# SIL Open Font License shipped with the site fonts, as the licence requires)
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "out", "cache", "lib"}
INTERNAL_NOTES = {"CRITIQUE.md", "PROJECT-STATE.md", "CLAUDE.md"}
# a word boundary keeps hex such as 0x402... in raw chain data from matching
EARLIER_PROJECT = re.compile("|".join(r"\b" + w[::-1] for w in ("204x", "yrotavresbo")), re.IGNORECASE)


def tracked_files(include_legal: bool = False) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        paths = [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        paths = list(ROOT.rglob("*"))
    return [
        p for p in paths
        if p.is_file()
        and p.suffix.lower() in TEXT_SUFFIXES
        and not (set(p.relative_to(ROOT).parts) & SKIP_PARTS)
        and (include_legal or p.name not in LEGAL_TEXTS)
    ]


def _text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def test_no_forbidden_words_in_repository_files():
    hits = []
    for p in tracked_files():
        text = _text(p)
        if text is None:
            continue
        hits += [f"{p.relative_to(ROOT)}:{line}: {w!r}" for line, w in scan(text)]
    assert not hits, "forbidden words found:\n" + "\n".join(hits[:40])


def test_no_forbidden_words_in_commit_messages():
    try:
        log = subprocess.run(
            ["git", "log", "--format=%H %B"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return  # no commits yet, or not a checkout
    hits = [f"{line}: {w!r}" for line, w in scan(log)]
    assert not hits, "forbidden words in commit messages:\n" + "\n".join(hits[:20])


def test_earlier_project_not_named_outside_internal_notes():
    hits = []
    for p in tracked_files(include_legal=True):
        rel = p.relative_to(ROOT)
        if rel.name in INTERNAL_NOTES or rel.parts[0] == "tests":
            continue
        text = _text(p)
        if text and EARLIER_PROJECT.search(text):
            hits.append(str(rel))
    assert not hits, "the earlier project is named in: " + ", ".join(hits)


def test_scan_examples():
    assert scan("forced " + "gnilles"[::-1]) and scan("Go " + "gnol"[::-1]) and scan("thread " + "EFAS"[::-1])
    assert not scan("liquidation flow; shortfall; as long as it holds; safe_div; threshold; selloff-free")
