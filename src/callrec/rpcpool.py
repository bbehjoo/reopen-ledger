"""Endpoint fallback: one role (config/chain.yaml `rpc`), several keyless endpoints, tried in order.

A request moves to the next endpoint when the current one refuses it in a way retrying cannot fix: HTTP
401/403, an answer saying the range needs archive access or a key ("archive", "personal token", "api key",
"older than"), or a rate limit that outlasted its retries. Measured 2026-11-08: publicnode serves logs for
recent months only (August 2026 blocks need a token), so old ranges go to dRPC.
"""

from __future__ import annotations

import logging

from .rpc import RateLimited, Rpc, RpcAuthError, RpcError, rpc_host

log = logging.getLogger(__name__)
REFUSAL_PHRASES = ("archive", "personal token", "api key", "older than", "not supported", "discontinued")
MIN_INTERVAL = {"base-rpc.publicnode.com": 0.25, "mainnet.base.org": 0.3, "base.drpc.org": 0.6,
                "gateway.tenderly.co": 0.6, "sepolia.base.org": 0.3, "base-sepolia-rpc.publicnode.com": 0.3}


def _refused(e: RpcError) -> bool:
    if isinstance(e, RpcAuthError | RateLimited):
        return True
    m = (e.message or "").lower()
    return any(p in m for p in REFUSAL_PHRASES)


class RpcPool:
    def __init__(self, urls: list[str], max_retries: int = 6):
        self.rpcs = [Rpc(u, min_interval=MIN_INTERVAL.get(rpc_host(u), 0.5), max_retries=max_retries)
                     for u in urls]
        self.host = ",".join(r.host for r in self.rpcs)

    def _try(self, fn_name: str, *args, **kw):
        last: RpcError | None = None
        for r in self.rpcs:
            try:
                return getattr(r, fn_name)(*args, **kw)
            except RpcError as e:
                if not _refused(e):
                    raise
                log.info("%s refused %s (%s); trying the next endpoint", r.host, fn_name, e.message[:80])
                last = e
        assert last is not None
        raise last

    def call(self, method, params=None):
        return self._try("call", method, params)

    def batch(self, calls):
        return self._try("batch", calls)

    def block_number(self):
        return self._try("block_number")

    def get_block(self, number, full_txs=False):
        return self._try("get_block", number, full_txs)

    def eth_call(self, to, data, block="latest"):
        return self._try("eth_call", to, data, block)

    def get_logs(self, address, topics, from_block, to_block):
        return self._try("get_logs", address, topics, from_block, to_block)

    def close(self):
        for r in self.rpcs:
            r.close()
