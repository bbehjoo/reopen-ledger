import os

import pytest
import yaml
from dotenv import dotenv_values

from callrec import config, house


def listed():
    return yaml.safe_load((config.config_dir() / "house.yaml").read_text(encoding="utf-8"))["wallets"]


def test_roles_are_strings_in_order():
    assert [w["role"] for w in listed()] == list(house.ROLES)
    assert [w["index"] for w in listed()] == list(range(len(house.ROLES)))


def test_listed_addresses_are_the_derived_ones():
    m = os.environ.get(house.ENV_VAR) or dotenv_values(config.ROOT / ".env").get(house.ENV_VAR)
    if not m:
        pytest.skip("no house mnemonic in this environment")
    got = {w.role: w.address for w in house.addresses(m)}
    assert {w["role"]: w["address"] for w in listed()} == got
