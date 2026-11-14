"""The AgentKit examples encode commit calldata byte for byte like the reference (callrec.commits and the
ERC-8021 suffix of callrec.attribution). The TypeScript one runs under plain Node (type stripping, Node 22.6+);
it is skipped where Node is missing or too old."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from callrec import attribution
from callrec.commits import Call, commit_calldata, encode_calls

ROOT = Path(__file__).resolve().parents[1]
CALLS = [{"token": "0xb20000000000000000000078ee7ce2fe4908108c", "p": 0.62},
         {"token": "0xb2000000000000000000001e800a7f5189430cd0", "p": 0.41},
         {"token": "0xb2000000000000000000002d0ba3164cc74f58b7", "p": 0.12345}]   # an exact half at 1e4
WINDOW = 120261120
CODES = ["bc_test123"]


def _reference() -> str:
    data = encode_calls([Call(c["token"], int(c["p"] * 10000 + 0.5), None) for c in CALLS])
    return commit_calldata(WINDOW, 1, data, attribution.to_suffix(CODES + ["bc_akq83qpj"]))


def test_python_agentkit_example_matches_reference():
    spec = importlib.util.spec_from_file_location("rl_action", ROOT / "examples" / "agentkit" / "reopen_ledger_action.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.encode(WINDOW, CALLS, CODES) == _reference()


def _node_ok() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return (int(out[0]), int(out[1])) >= (22, 6)


@pytest.mark.skipif(not _node_ok(), reason="needs Node 22.6+ to run TypeScript directly")
def test_typescript_agentkit_example_matches_reference():
    src = (ROOT / "examples" / "agentkit" / "encode.ts").as_uri()
    js = (f"import({json.dumps(src)}).then(m => process.stdout.write("
          f"m.encode({WINDOW}, {json.dumps(CALLS)}, {json.dumps(CODES)})))")
    out = subprocess.run(["node", "--no-warnings", "-e", js], capture_output=True, text=True, check=True).stdout
    assert out == _reference()
