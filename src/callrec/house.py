"""House wallets: one mnemonic, one derived account per role.

The mnemonic lives in `.env` as HOUSE_MNEMONIC (gitignored) or in the CI secret of the same name. It is
never printed, logged or written anywhere else. Only addresses leave this module.

Roles (BIP-44 path m/44'/60'/0'/0/<index>):
  0 anchor       funded by the operator; posts the daily anchor and tops up the other house wallets
  1 null         commits p = 0.5 on every slate token
  2 persistence  commits the "no change" forecast (Friday close)
  3 dex_implied  commits the probability implied by the DEX price against the frozen reference
  4 coverage     commits the Friday coverage call (schema 2)

Every house wallet is labelled on the site and excluded from every traction figure (METHODS.md §7).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from eth_account import Account

Account.enable_unaudited_hdwallet_features()

ROLES = ("anchor", "null", "persistence", "dex_implied", "coverage")
ENV_VAR = "HOUSE_MNEMONIC"


@dataclass(frozen=True)
class HouseWallet:
    role: str
    index: int
    address: str


def _path(index: int) -> str:
    return f"m/44'/60'/0'/0/{index}"


def mnemonic_from_env() -> str:
    m = os.environ.get(ENV_VAR, "").strip()
    if not m:
        raise RuntimeError(f"{ENV_VAR} is not set (see docs/RUNBOOK.md)")
    return m


def derive(mnemonic: str, role: str):
    """The LocalAccount for a role. Callers sign with it and never print it."""
    return Account.from_mnemonic(mnemonic, account_path=_path(ROLES.index(role)))


def addresses(mnemonic: str) -> list[HouseWallet]:
    return [HouseWallet(r, i, derive(mnemonic, r).address) for i, r in enumerate(ROLES)]


def new_mnemonic() -> str:
    _, m = Account.create_with_mnemonic(num_words=24)
    return m
