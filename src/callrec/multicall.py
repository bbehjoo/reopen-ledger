"""Multicall3 `aggregate3` (0xcA11bde05977b3631167028862bE2a173976CA11, the same address on Base) for reading
many views in one eth_call. Failures are returned as None, never raised."""

from __future__ import annotations

from eth_abi import decode, encode
from eth_utils import to_checksum_address

MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
AGGREGATE3 = "0x82ad56cb"


def aggregate(rpc, calls: list[tuple[str, str]], block: int | str = "latest", chunk: int = 200) -> list[str | None]:
    """calls: (target, calldata hex). Returns each call's return data as hex, or None when it failed."""
    out: list[str | None] = []
    for i in range(0, len(calls), chunk):
        part = calls[i: i + chunk]
        args = [(to_checksum_address(t), True, bytes.fromhex(d.removeprefix("0x"))) for t, d in part]
        data = AGGREGATE3 + encode(["(address,bool,bytes)[]"], [args]).hex()
        ret = rpc.eth_call(MULTICALL3, data, block)
        (results,) = decode(["(bool,bytes)[]"], bytes.fromhex(ret.removeprefix("0x")))
        out += ["0x" + r.hex() if ok and r else None for ok, r in results]
    return out
