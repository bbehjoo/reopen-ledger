"""Tiny ABI helpers: selectors, word decoding, and the int24/int256 casts pool math needs."""

from __future__ import annotations

from functools import cache

from eth_utils import keccak


@cache
def selector(sig: str) -> str:
    return "0x" + keccak(text=sig).hex()[:8]


@cache
def topic(sig: str) -> str:
    return "0x" + keccak(text=sig).hex()


def words(hexdata: str) -> list[int]:
    raw = bytes.fromhex(hexdata[2:] if hexdata.startswith("0x") else hexdata)
    return [int.from_bytes(raw[i: i + 32], "big") for i in range(0, len(raw), 32)]


def signed(v: int, bits: int = 256) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def decode_uint(hexdata: str) -> int:
    w = words(hexdata)
    return w[0] if w else 0


def decode_address(word: int | str) -> str:
    if isinstance(word, str):
        word = int(word, 16)
    return "0x" + f"{word:064x}"[-40:]


def decode_string(hexdata: str) -> str:
    raw = bytes.fromhex(hexdata[2:])
    if len(raw) < 64:
        return raw.rstrip(b"\x00").decode("utf-8", "replace")
    offset = int.from_bytes(raw[:32], "big")
    length = int.from_bytes(raw[offset: offset + 32], "big")
    return raw[offset + 32: offset + 32 + length].decode("utf-8", "replace")


def enc_uint(v: int) -> str:
    return f"{v % (1 << 256):064x}"


def enc_address(a: str) -> str:
    return a.lower().removeprefix("0x").rjust(64, "0")


def call_data(sig: str, *args_hex: str) -> str:
    return selector(sig) + "".join(args_hex)
