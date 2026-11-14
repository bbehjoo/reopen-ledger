"""Offchain snapshots (METHODS.md section 2b): the issuer's token list, its public token page and the feed
directory, fetched once a day. The copies stay private (data/private/, gitignored); what is kept on the
record is the URL, the fetch time, the HTTP status, the byte length and the SHA-256 of each copy
(data/raw/offchain/index.jsonl), so a later change of any page can be shown to have happened.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime

import httpx

from . import config
from .rpc import USER_AGENT

SOURCES = [
    ("tokens_api", "https://api.coinbase.com/v1/tokenized-stocks"),
    ("stocks_page", "https://www.base.org/stocks"),
    ("integration_docs", "https://docs.base.org/build-on-base/integrate-defi/list-tokenized-stocks"),
    ("feed_directory", "https://reference-data-directory.vercel.app/feeds-ethereum-mainnet-base-1.json"),
]


def snapshot(sources=SOURCES) -> list[dict]:
    now = datetime.now(UTC)
    day = now.strftime("%Y-%m-%d")
    priv = config.data_dir() / "private" / "offchain" / day
    priv.mkdir(parents=True, exist_ok=True)
    idx = config.data_dir() / "raw" / "offchain"
    idx.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=60, headers={"user-agent": USER_AGENT}, follow_redirects=True) as c:
        for name, url in sources:
            try:
                r = c.get(url)
                body, status = r.content, r.status_code
            except httpx.HTTPError as e:
                body, status = b"", f"error:{type(e).__name__}"
            h = hashlib.sha256(body).hexdigest()
            (priv / f"{name}.bin").write_bytes(body)
            rows.append({"name": name, "url": url, "fetched_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "status": status, "bytes": len(body), "sha256": h})
            time.sleep(0.5)
    with (idx / "index.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return rows
