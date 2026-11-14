"""ERC-8021 attribution suffix, schema 0 (the layout in ox/erc8021 Attribution.ts, ox 0.14.63):

    codes (ASCII, comma-joined) || codesLength (1 byte) || schemaId 0x00 (1 byte) || 0x8021 x 8 (16 bytes)

appended after the ABI-encoded calldata. Contracts ignore it; Base's indexers read it. Several codes in one
suffix credit each of them (a wallet, an agent framework, this project).
"""

from __future__ import annotations

MARKER = bytes.fromhex("80218021802180218021802180218021")


def project_code() -> str | None:
    """This project's own Builder Code (config/attribution.yaml), or None before registration."""
    from . import config
    try:
        return (config.load_yaml("attribution.yaml") or {}).get("builder_code") or None
    except config.ConfigError:
        return None


def to_suffix(codes: list[str]) -> bytes:
    raw = ",".join(codes).encode("ascii")
    if len(raw) > 255:
        raise ValueError("codes too long for a one-byte length")
    return raw + bytes([len(raw), 0]) + MARKER


def from_calldata(data: bytes | str) -> list[str] | None:
    """The codes of a schema-0 suffix at the end of `data`, or None when there is none."""
    if isinstance(data, str):
        data = bytes.fromhex(data.removeprefix("0x"))
    if len(data) < 18 or data[-16:] != MARKER:
        return None
    if data[-17] != 0:
        return None  # another schema: not decoded here
    n = data[-18]
    if len(data) < 18 + n:
        return None
    codes = data[-18 - n: -18].decode("ascii", "replace")
    return codes.split(",") if codes else []
