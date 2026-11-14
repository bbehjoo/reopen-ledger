"""Config files under config/ (overridable with CALLREC_CONFIG for tests), and the data root (CALLREC_DATA)."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    pass


def config_dir() -> Path:
    return Path(os.environ.get("CALLREC_CONFIG", ROOT / "config"))


def data_dir() -> Path:
    return Path(os.environ.get("CALLREC_DATA", ROOT / "data"))


def load_yaml(name: str) -> Any:
    p = config_dir() / name
    if not p.exists():
        raise ConfigError(f"missing config file {p}")
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(name: str) -> Any:
    p = config_dir() / name
    if not p.exists():
        raise ConfigError(f"missing config file {p}")
    return json.loads(p.read_text(encoding="utf-8"))


@cache
def chain() -> dict:
    return load_yaml("chain.yaml")


def rpc_urls(role: str) -> list[str]:
    env = os.environ.get(f"RPC_{role.upper()}")
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    urls = chain()["rpc"].get(role)
    if not urls:
        raise ConfigError(f"no RPC endpoints for role {role!r}")
    return list(urls)
