"""Minimal JSON-RPC client for Base tuned to free endpoints.

Adapted from the author's earlier Apache-2.0 code on 2026-11-08; the endpoint notes below date from
then. This project's endpoint roles and their measured limits are in config/chain.yaml.

Endpoints in use (2026-10-25):

* rpc-base.blockmachine.io, the keyless primary: archive; eth_getLogs over at most 10,000 blocks
  (inclusive) and 20,000 results, 1 RU per call, 60 RU/min fair use, so calls are paced 1 s apart by
  default (`default_min_interval`); JSON-RPC batches work. A dense window answers HTTP 200 with
  -32602 "query exceeds max results 20000, retry with the range A-B"; a wide one with -32602 "block
  range exceeds maximum allowed (max=10000, ...)" and `data.max_blocks`.
* mainnet.base.org (2026-09-01): getLogs over 2,000 blocks is fine, 10,000 fails; at most 10 calls
  per batch; topic OR-arrays of 500 entries are fine; a User-Agent header is required (403 without).
  It lowered its limits on 2026-10-08 and now answers -32011 "request limit reached".
* fallbacks (Ankr, Infura, dRPC) answer range errors with their own codes, listed below.

Every error is handled by kind:

* rate limits (HTTP 429; JSON-RPC -32016 "over rate limit", -32005 "limit exceeded", -32011
  "request limit reached" with HTTP 429 or 200, as a single answer or a batch item; any message
  saying "rate limit" or "too many requests") are retried with exponential backoff and jitter and,
  once the retries are spent, raise `RateLimited`. They never shrink a getLogs window: a narrower
  range costs more calls, not fewer.
* range errors (block range too wide, result set or response too large, query timeout; Blockmachine
  -32602 with a suggested range, Infura -32005 "query returned more than 10000 results", Ankr -32062,
  dRPC code 35) split the getLogs window: at the sub-range the node suggests when it names one that
  starts at the window's first block, otherwise in halves. No request spans more than
  MAX_LOG_WINDOW blocks.
* transient node errors (-32011 "no backend is currently healthy", "try again") are retried.
* HTTP 401/403 raise `RpcAuthError` at once (a wrong or missing key, or a refused client: retrying
  cannot help, so callers stop); other HTTP failures raise `RpcHttpError`, and transport failures
  that outlast the retries raise `RpcTransportError`.

The endpoint URL may carry an API key, so it is never part of an error, a log line or a traceback:
errors name the HTTP status or the exception type only, and httpx's own request log line is redacted
(`_UrlRedactor`). Show `Rpc.host` when an endpoint has to be named.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__
from .identity import DOMAIN, NAME

log = logging.getLogger(__name__)


def user_agent(name: str = NAME, domain: str = DOMAIN, version: str = __version__) -> str:
    """`<name>/<major.minor> (+https://<domain>/methods)`: the User-Agent of every request this package
    sends. While `callrec.identity` holds placeholders, so does this string."""
    return f"{name}/{'.'.join(version.split('.')[:2])} (+https://{domain}/methods)"


USER_AGENT = user_agent()
MAX_BATCH = 10
DEFAULT_LOG_WINDOW = 2000
MAX_LOG_WINDOW = 10_000  # blocks per eth_getLogs request, inclusive (Blockmachine's cap; the tightest in use)
MAX_TOPIC_OR = 500

# min seconds between calls when the caller gives none: an endpoint's published fair-use rate
HOST_MIN_INTERVAL = {"rpc-base.blockmachine.io": 1.0}  # 60 RU/min keyless, 1 RU per call
# eth_getLogs address-list caps (publicnode, 2026-11-08: "A maximum of 10 addresses is allowed")
HOST_MAX_ADDRESSES = {"base-rpc.publicnode.com": 10, "base-sepolia-rpc.publicnode.com": 10}

AUTH_STATUS = (401, 403)
RATE_LIMIT_CODES = (-32016, -32005)  # mainnet.base.org "over rate limit"; EIP-1474 "limit exceeded"
RATE_LIMIT_PHRASES = (
    "rate limit",
    "too many requests",
    "rate exceeded",
    "request rate",
    "request limit reached",  # mainnet.base.org -32011, with HTTP 429 or 200
)
RANGE_CODES = (-32062, 35)  # Ankr "block range / batch too large"; dRPC free-tier range limit
RANGE_PHRASES = (
    "range",  # "block range too large", "exceed maximum block range"
    "query returned more",
    "returned more than",
    "too many results",
    "too many logs",
    "too large",  # "response too large" (-32011 / -32020)
    "response size",
    "result size",
    "max results",
    "timeout",
    "timed out",
)
TRANSIENT_PHRASES = ("no backend", "service unavailable", "try again", "temporarily unavailable",
                     "node error", "upstream", "internal error", "header not found")
RETRY_STATUS = (408, 500, 502, 503, 504)
RETRY_AFTER_MAX_S = 300.0


class RpcError(RuntimeError):
    """A JSON-RPC error answer (`code`, `message`, `data` as the node sent them) or a failure to get one."""

    def __init__(self, code: int | None, message: str, data: Any = None):
        super().__init__(f"rpc error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class RateLimited(RpcError):
    """The node kept rate-limiting a request through every retry (HTTP 429 or a JSON-RPC rate limit).

    Distinct from a range error on purpose: the remedy is to wait or stop, never to split the request.
    """


class RpcHttpError(RpcError):
    """An HTTP failure without a JSON-RPC answer; `code` is the HTTP status. Never names the endpoint."""


class RpcAuthError(RpcHttpError):
    """HTTP 401/403: the node refused this client (a wrong or missing key, a missing User-Agent).

    Retrying cannot help, so callers stop instead of counting the request as a failed lookup.
    """


class RpcTransportError(RpcError):
    """The request could not be sent or answered (DNS, TCP, TLS, timeout) through every retry."""


def rpc_host(url: str) -> str:
    """The host of an endpoint URL: what may be shown or logged (the path or query may hold a key)."""
    try:
        return (urlsplit(url).hostname or "").lower() or "?"
    except ValueError:
        return "?"


def default_min_interval(url: str) -> float | None:
    """Seconds between calls an endpoint asks for (HOST_MIN_INTERVAL), or None when it publishes none."""
    return HOST_MIN_INTERVAL.get(rpc_host(url))


class _UrlRedactor(logging.Filter):
    """Replaces registered endpoint URLs in httpx's records ("HTTP Request: POST <url> ...", INFO).

    The CLI keeps the httpx logger at WARNING; this holds even when a caller turns it up."""

    def __init__(self) -> None:
        super().__init__()
        self.secrets: set[str] = set()

    def add(self, url: str) -> None:
        self.secrets.add(url)
        try:
            self.secrets.add(str(httpx.URL(url)))  # the form httpx prints
        except Exception:  # an unparsable URL fails at the first request instead
            pass
        self.secrets.discard("")

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        red = msg
        for s in sorted(self.secrets, key=len, reverse=True):
            red = red.replace(s, "<rpc url>")
        if red != msg:
            record.msg, record.args = red, None
        return True


_REDACTOR = _UrlRedactor()
logging.getLogger("httpx").addFilter(_REDACTOR)


class Rpc:
    def __init__(
        self,
        url: str,
        timeout: float = 60.0,
        max_retries: int = 8,
        min_interval: float = 0.0,
        *,
        transport: httpx.BaseTransport | None = None,
        backoff_base: float = 0.5,
        backoff_cap: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._url = url  # private: may hold a key; never logged, never part of an error
        self.host = rpc_host(url)
        _REDACTOR.add(url)
        self.max_retries = max_retries
        self.min_interval = min_interval
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._sleep = sleep
        self._next = 0.0  # monotonic time before which the next call waits
        self._id = 0
        self.calls = 0
        self.rate_limited = 0  # rate-limited responses seen (each one was waited out or reported)
        self.client = httpx.Client(
            timeout=timeout,
            headers={"user-agent": USER_AGENT, "content-type": "application/json"},
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"Rpc(host={self.host!r}, min_interval={self.min_interval})"

    # -- pacing ----------------------------------------------------------------------------------
    def _wait(self, attempt: int, floor: float = 0.0) -> float:
        """Exponential backoff with equal jitter: half of the step is fixed, half random."""
        step = min(self.backoff_cap, self.backoff_base * 2**attempt)
        delay = max(floor, step / 2 + random.uniform(0, step / 2))
        self._sleep(delay)
        return delay

    def _throttle(self, units: int = 1) -> None:
        """At least `min_interval` seconds per call: a batch of n calls holds the next request n intervals."""
        wait = self._next - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._next = time.monotonic() + self.min_interval * max(1, units)

    # -- transport -------------------------------------------------------------------------------
    def _post(self, payload: Any) -> Any:
        """POST one JSON-RPC payload; returns the parsed body. Every error raised here is URL-free and
        raised outside any `except` block, so no traceback chains back to an httpx error (whose request
        carries the URL)."""
        attempt = 0  # transport failures, 5xx, unparsable bodies
        limited = 0  # HTTP 429
        units = len(payload) if isinstance(payload, list) else 1
        while True:
            self._throttle(units)
            self.calls += 1
            failure, retriable = None, True
            try:
                r = self.client.post(self._url, json=payload)
            except httpx.TransportError as e:
                failure, retriable = type(e).__name__, True
            except (httpx.HTTPError, httpx.InvalidURL) as e:  # not sendable as configured
                failure, retriable = type(e).__name__, False
            if failure is not None:
                if not retriable or attempt >= self.max_retries:
                    raise RpcTransportError(None, f"{failure} after {attempt + 1} attempt(s)")
                delay = self._wait(attempt)
                log.warning("rpc transport retry %d after %s (%.1fs)", attempt + 1, failure, delay)
                attempt += 1
                continue
            status = r.status_code
            if status in AUTH_STATUS:
                raise RpcAuthError(
                    status, f"HTTP {status}: the node refused this client (check the RPC URL and its key)"
                )
            if status == 429:
                self.rate_limited += 1
                if limited >= self.max_retries:
                    raise RateLimited(429, f"HTTP 429 after {limited + 1} attempts")
                delay = self._wait(limited, floor=_retry_after(r))
                log.warning("rpc rate limited (HTTP 429); retry %d in %.1fs", limited + 1, delay)
                limited += 1
                continue
            if status != 200:
                # some nodes wrap JSON-RPC errors (e.g. -32020 "backend response too large") in HTTP 500;
                # those are answers, not transport failures, and must not be retried verbatim
                body = _try_json(r)
                if body is not None:
                    return body
                if status in RETRY_STATUS and attempt < self.max_retries:
                    delay = self._wait(attempt)
                    log.warning("rpc HTTP %d; retry %d in %.1fs", status, attempt + 1, delay)
                    attempt += 1
                    continue
                raise RpcHttpError(status, f"HTTP {status}")
            body, parsed = _parse_json(r)
            if parsed:
                return body
            if attempt >= self.max_retries:
                raise RpcHttpError(status, f"HTTP {status} with a body that is not JSON")
            self._wait(attempt)
            attempt += 1

    def call(self, method: str, params: list | None = None) -> Any:
        limited = transient = 0
        while True:
            self._id += 1
            res = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []})
            if not isinstance(res, dict):
                raise RpcError(None, f"non-object response: {str(res)[:200]}")
            err = res.get("error")
            if not err:
                return res.get("result")
            e = _rpc_error(err)
            if _is_rate_limit(e):
                self.rate_limited += 1
                if limited >= self.max_retries:
                    raise RateLimited(e.code, e.message)
                delay = self._wait(limited)
                log.warning("rpc rate limited (%s); retry %d in %.1fs", e.code, limited + 1, delay)
                limited += 1
                continue
            if _is_transient(e) and transient < self.max_retries:
                delay = self._wait(transient)
                log.warning(
                    "rpc transient error %s (%s); retry %d in %.1fs", e.code, e.message, transient + 1, delay
                )
                transient += 1
                continue
            raise e

    def batch(self, calls: list[tuple[str, list]]) -> list[Any]:
        """Run calls in batches of MAX_BATCH; returns results in order (RpcError instances for failures).

        The public node rate-limits *per item* inside a batch (-32016 "over rate limit", HTTP 200);
        rate-limited items are re-issued with backoff, and items still rate-limited when the retries
        are spent come back as `RateLimited` instances. Everything else is returned as-is.
        """
        out: list[Any] = [None] * len(calls)
        pending = list(range(len(calls)))
        attempt = 0
        while pending:
            retry: list[int] = []
            for i in range(0, len(pending), MAX_BATCH):
                idxs = pending[i : i + MAX_BATCH]
                payload = []
                for j in idxs:
                    self._id += 1
                    method, params = calls[j]
                    payload.append({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
                res = self._post(payload)
                if not isinstance(res, list):
                    # some nodes answer a batch with a single error object
                    err = res.get("error") if isinstance(res, dict) else None
                    e = _rpc_error(err) if err else None
                    if e is not None and _is_rate_limit(e):
                        for j in idxs:
                            out[j] = RateLimited(e.code, e.message)
                        retry.extend(idxs)
                        continue
                    msg = res.get("error", res) if isinstance(res, dict) else res
                    raise RpcError(None, f"batch rejected: {str(msg)[:200]}")
                by_id = {item["id"]: item for item in res if isinstance(item, dict) and "id" in item}
                for j, p in zip(idxs, payload, strict=True):
                    item = by_id.get(p["id"])
                    if item is None:
                        out[j] = RpcError(None, "missing batch item")
                    elif item.get("error"):
                        e = _rpc_error(item["error"])
                        if _is_rate_limit(e):
                            out[j] = RateLimited(e.code, e.message)
                            retry.append(j)
                        else:
                            out[j] = e
                    else:
                        out[j] = item.get("result")
            if not retry:
                break
            self.rate_limited += len(retry)
            if attempt >= self.max_retries:
                break  # the items keep their RateLimited error
            self._wait(attempt)
            attempt += 1
            pending = retry
        return out

    # -- helpers ----------------------------------------------------------------------------------
    def block_number(self) -> int:
        return int(self.call("eth_blockNumber"), 16)

    def chain_id(self) -> int:
        return int(self.call("eth_chainId"), 16)

    def get_block(self, number: int, full_txs: bool = False) -> dict | None:
        return self.call("eth_getBlockByNumber", [hex(number), full_txs])

    def eth_call(self, to: str, data: str, block: int | str = "latest") -> str:
        tag = hex(block) if isinstance(block, int) else block
        return self.call("eth_call", [{"to": to, "data": data}, tag])

    def get_logs(self, address: str | list[str], topics: list, from_block: int, to_block: int) -> list[dict]:
        """eth_getLogs over [from_block, to_block] in block order, in requests of at most MAX_LOG_WINDOW
        blocks. A range rejection splits the request at the sub-range the node suggests (one that starts
        at the request's first block) or in halves; a rate limit never splits (waiting is the remedy).
        Address lists longer than the host allows (publicnode: 10) are split into groups and merged in
        (block, logIndex) order."""
        cap = HOST_MAX_ADDRESSES.get(self.host)
        if isinstance(address, list) and cap and len(address) > cap:
            merged: list[dict] = []
            for i in range(0, len(address), cap):
                merged += self.get_logs(address[i: i + cap], topics, from_block, to_block)
            merged.sort(key=lambda x: (int(x["blockNumber"], 16), int(x["logIndex"], 16)))
            return merged
        out: list[dict] = []
        pending = [
            (a, min(a + MAX_LOG_WINDOW - 1, to_block))
            for a in range(from_block, to_block + 1, MAX_LOG_WINDOW)
        ]
        pending.reverse()  # a stack: the lowest range on top
        while pending:
            a, b = pending.pop()
            learned = getattr(self, "learned_window", None)
            if learned and b - a + 1 > learned:  # a node that named its cap: never ask for more again
                pending.append((a + learned, b))
                b = a + learned - 1
            params = {"address": address, "topics": topics, "fromBlock": hex(a), "toBlock": hex(b)}
            try:
                res = self.call("eth_getLogs", [params])
            except RateLimited:
                raise
            except RpcError as e:
                if b > a and _looks_like_range_error(e):
                    cut = _suggested_end(e, a, b)
                    mid = (a + b) // 2 if cut is None else cut
                    if cut is not None and "block range" in (str(e.data) + e.message).lower():
                        self.learned_window = cut - a + 1
                    log.info(
                        "splitting getLogs window %d-%d at %d (%s) after: %s",
                        a,
                        b,
                        mid,
                        "half" if cut is None else "suggested",
                        e.message[:100],
                    )
                    pending.append((mid + 1, b))
                    pending.append((a, mid))
                    continue
                raise
            out.extend(res or [])
        return out

    def get_logs_topic_or(
        self, address: str, topic0: str, position: int, values: list[str], from_block: int, to_block: int
    ) -> list[dict]:
        """Filter on topic0 and an OR-array at `position` (1..3), chunking the OR-array to MAX_TOPIC_OR."""
        out: list[dict] = []
        vals = sorted(set(values))
        for i in range(0, len(vals), MAX_TOPIC_OR):
            chunk = vals[i : i + MAX_TOPIC_OR]
            topics: list = [topic0] + [None] * (position - 1) + [chunk]
            out.extend(self.get_logs(address, topics, from_block, to_block))
        return out

    def get_transactions(self, tx_hashes: list[str]) -> dict[str, dict | RpcError | None]:
        """tx hash -> transaction; None when the node answered null (it does not know the transaction);
        the RpcError when the lookup failed (an error answer, or a rate limit that outlasted the retries)."""
        res = self.batch([("eth_getTransactionByHash", [h]) for h in tx_hashes])
        return dict(zip(tx_hashes, res, strict=True))

    def close(self) -> None:
        self.client.close()


def _parse_json(r: httpx.Response) -> tuple[Any, bool]:
    """(body, True) when the response body is JSON, (None, False) otherwise; never raises."""
    try:
        return r.json(), True
    except ValueError:
        return None, False


def _try_json(r: httpx.Response) -> Any | None:
    body, parsed = _parse_json(r)
    if not parsed:
        return None
    if isinstance(body, dict) and ("error" in body or "result" in body):
        return body
    if isinstance(body, list):
        return body
    return None


def _retry_after(r: httpx.Response) -> float:
    """Seconds asked for by a Retry-After header (the numeric form only), capped; 0 when absent."""
    try:
        return min(max(0.0, float(r.headers.get("retry-after", "0"))), RETRY_AFTER_MAX_S)
    except ValueError:
        return 0.0


def _rpc_error(err: Any) -> RpcError:
    if isinstance(err, dict):
        code = err.get("code")
        return RpcError(
            code if isinstance(code, int) and not isinstance(code, bool) else None,
            str(err.get("message") or err),
            err.get("data"),
        )
    return RpcError(None, str(err))


def _is_rate_limit(e: RpcError) -> bool:
    if isinstance(e, RateLimited):
        return True
    m = e.message.lower()
    if any(p in m for p in RATE_LIMIT_PHRASES):
        return True
    if e.code in RATE_LIMIT_CODES:
        # -32005 also carries result-size limits ("query returned more than 10000 results"): those split
        return not _looks_like_range_error(e)
    return e.code == 429


def _is_transient(e: RpcError) -> bool:
    """Server-side hiccups of the public node that answer as JSON-RPC errors (-32011 "no backend is
    currently healthy to serve traffic"); a 10-hour backfill must outlive them. A -32011 that says the
    response is too large is a range error instead, and one that says "request limit reached" a rate
    limit: retrying the same window at once cannot succeed."""
    if _looks_like_range_error(e) or _is_rate_limit(e):
        return False
    m = e.message.lower()
    return e.code == -32011 or any(p in m for p in TRANSIENT_PHRASES)


def _looks_like_range_error(e: RpcError) -> bool:
    """A JSON-RPC answer saying the getLogs window is too wide or its result too large (never an HTTP
    or transport failure, never a rate limit)."""
    if isinstance(e, RpcHttpError | RpcTransportError):
        return False
    # Tenderly answers -32602 "invalid params" and puts "Block range too large ..." in `data`
    m = (e.message + " " + (e.data if isinstance(e.data, str) else "")).lower()
    if any(p in m for p in RATE_LIMIT_PHRASES):
        return False
    return e.code in RANGE_CODES or any(p in m for p in RANGE_PHRASES)


# The sub-range a node names in a range rejection, as (first, last) block:
_SUGGESTED_RANGES = (
    # Blockmachine: "query exceeds max results 20000, retry with the range 50776287-50776516"
    re.compile(r"\brange (\d+)\s*-\s*(\d+)\b"),
    # Infura: "... Try with this block range [0x14D0E14, 0x14D1E7A]."; Alchemy: "... should work: [0x.., 0x..]"
    re.compile(r"\[\s*(0x[0-9a-fA-F]+)\s*,\s*(0x[0-9a-fA-F]+)\s*\]"),
)


def _block_number(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v, 16) if v.lower().startswith("0x") else int(v)
        except ValueError:
            return None
    return None


def _suggested_end(e: RpcError, a: int, b: int) -> int | None:
    """Last block of the first sub-range of [a, b] the node suggests: a range named in the message or in
    `data` (`from`/`to`, Infura) that starts at `a` and ends before `b`, or `a + data.max_blocks - 1`
    (Blockmachine). None when the node names nothing usable (the caller halves instead)."""
    candidates: list[tuple[int | None, int | None]] = []
    text = e.message + " " + (e.data if isinstance(e.data, str) else "")
    for rx in _SUGGESTED_RANGES:
        m = rx.search(text)
        if m:
            candidates.append((_block_number(m.group(1)), _block_number(m.group(2))))
    data = e.data if isinstance(e.data, dict) else {}
    if "from" in data and "to" in data:
        candidates.append((_block_number(data["from"]), _block_number(data["to"])))
    max_blocks = _block_number(data.get("max_blocks"))
    if max_blocks is not None and max_blocks > 0:
        candidates.append((a, a + max_blocks - 1))
    for lo, hi in candidates:
        if lo == a and hi is not None and a <= hi < b:
            return hi
    return None


def decode_abi_string(hexdata: str) -> str:
    raw = bytes.fromhex(hexdata[2:])
    if len(raw) < 64:
        return raw.rstrip(b"\x00").decode("utf-8", "replace")
    offset = int.from_bytes(raw[:32], "big")
    length = int.from_bytes(raw[offset : offset + 32], "big")
    return raw[offset + 32 : offset + 32 + length].decode("utf-8", "replace")
