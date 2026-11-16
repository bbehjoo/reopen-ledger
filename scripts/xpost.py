"""Post to the project's X account (@reopenledger) through Zernio. Dry run unless --go is given.

    uv run python scripts/xpost.py --text "..." [--image URL | --video URL] [--at 2026-11-20T20:00:00-05:00] [--go]
    uv run python scripts/xpost.py --draft drafts/2026-11-16-unfreeze.md [--image URL] [--go]

Media is attached by public HTTPS URL (the site's cards are public). Only the X account in ZERNIO_X_ACCOUNT is
ever used; the key (ZERNIO_API_KEY) is read from .env and never printed. X counts a link as 23 characters.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://zernio.com/api/v1"


def env() -> dict:
    from dotenv import dotenv_values
    return dotenv_values(ROOT / ".env")


def draft_text(path: Path) -> str:
    """The post text of a ritual draft: the paragraph after the '---' line (before any 'Attach:')."""
    body = path.read_text(encoding="utf-8").split("\n---\n", 1)[-1]
    body = body.split("\nAttach:", 1)[0]
    return " ".join(body.split()).strip()


def x_length(text: str) -> int:
    return len(re.sub(r"https?://\S+", "x" * 23, text))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--draft")
    ap.add_argument("--image")
    ap.add_argument("--video")
    ap.add_argument("--at", help="ISO time with offset, e.g. 2026-11-20T20:00:00-05:00 (default: now)")
    ap.add_argument("--go", action="store_true", help="really post (default is a dry run)")
    a = ap.parse_args()
    text = a.text or (draft_text(ROOT / a.draft) if a.draft else None)
    if not text:
        ap.error("--text or --draft is required")
    if x_length(text) > 280:
        raise SystemExit(f"error: {x_length(text)} characters as X counts them (limit 280)")
    e = env()
    acct = e.get("ZERNIO_X_ACCOUNT")
    if not acct:
        raise SystemExit("error: ZERNIO_X_ACCOUNT is not set in .env")
    body: dict = {"content": text, "platforms": [{"platform": "twitter", "accountId": acct}]}
    media = [{"type": "image", "url": a.image}] if a.image else [{"type": "video", "url": a.video}] if a.video else []
    for m in media:
        if not m["url"].startswith("https://"):
            raise SystemExit("error: media must be a public https URL")
    if media:
        body["mediaItems"] = media
    if a.at:
        when = datetime.fromisoformat(a.at).astimezone(UTC)
        body["scheduledFor"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        body["publishNow"] = True
    print(json.dumps(body, indent=1))
    print(f"{x_length(text)} characters as X counts them")
    if not a.go:
        print("dry run: nothing posted (add --go)")
        return 0
    req = urllib.request.Request(f"{API}/posts", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {e['ZERNIO_API_KEY']}",
                                          "Content-Type": "application/json", "User-Agent": "reopen-ledger"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"error: HTTP {err.code}: {err.read()[:400]!r}") from None
    post = res.get("post", res)
    print("posted:", json.dumps({k: post.get(k) for k in ("_id", "status", "scheduledFor", "platforms") if k in post})[:800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
