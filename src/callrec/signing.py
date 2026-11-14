"""Canonical JSON (RFC 8785) and Ed25519 signatures over it; adapted from the author's earlier code.

The export signing key is EXPORT_SIGNING_KEY in .env or the CI secret (base64url of the raw 32-byte
Ed25519 private key); its public half is published in keys/export-key.json. A document is signed over the
canonical JSON of everything except its `signature` member.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ENV_VAR = "EXPORT_SIGNING_KEY"


def es6_number(x: float) -> str:
    """ES6 Number::toString for finite doubles (RFC 8785 section 3.2.2.3)."""
    if x == 0:
        return "0"
    if not math.isfinite(x):
        raise ValueError("non-finite numbers are not JSON")
    sign = "-" if x < 0 else ""
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:e([+-]\d+))?", repr(abs(x)))
    assert m, repr(x)
    int_part, frac_part, exp = m.group(1), m.group(2) or "", int(m.group(3) or 0)
    digits = (int_part + frac_part).lstrip("0")
    n = len(int_part) + exp - (len(int_part + frac_part) - len((int_part + frac_part).lstrip("0")))
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    mant = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{sign}{mant}e{'+' if e >= 0 else '-'}{abs(e)}"


def _canon(obj) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return es6_number(obj)
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list | tuple):
        return "[" + ",".join(_canon(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _canon(v) for k, v in items) + "}"
    raise TypeError(type(obj))


def canonical_json(obj) -> bytes:
    return _canon(obj).encode("utf-8")


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def raw_public(pk: Ed25519PublicKey) -> bytes:
    return pk.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(pk: Ed25519PublicKey) -> str:
    return hashlib.sha256(raw_public(pk)).hexdigest()[:16]


def key_from_env() -> Ed25519PrivateKey | None:
    v = os.environ.get(ENV_VAR, "").strip()
    return Ed25519PrivateKey.from_private_bytes(unb64u(v)) if v else None


def new_key_b64() -> str:
    k = Ed25519PrivateKey.generate()
    return b64u(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption()))


def public_doc(pk: Ed25519PublicKey) -> dict:
    return {"schema": "callrec-key/v1", "alg": "ed25519", "key_id": key_id(pk), "public_key": b64u(raw_public(pk))}


def sign_document(doc: dict, sk: Ed25519PrivateKey) -> dict:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return {**body, "signature": {"alg": "ed25519", "key_id": key_id(sk.public_key()),
                                  "sig": b64u(sk.sign(canonical_json(body)))}}


def verify_document(doc: dict, pk: Ed25519PublicKey) -> bool:
    sig = doc.get("signature") or {}
    if sig.get("alg") != "ed25519" or sig.get("key_id") != key_id(pk):
        return False
    body = {k: v for k, v in doc.items() if k != "signature"}
    try:
        pk.verify(unb64u(sig["sig"]), canonical_json(body))
        return True
    except Exception:
        return False
