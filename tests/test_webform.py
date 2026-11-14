"""The web form builds the same calldata as the Python encoder (checked by running commit.js under node)."""

import json
import shutil
import subprocess

import pytest

from callrec import attribution, commits
from callrec.commits import Call
from callrec.config import ROOT

NVDA = "0xb20000000000000000000078ee7ce2fe4908108c"
TSLA = "0xb2000000000000000000001e800a7f5189430cd0"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_form_calldata_matches_python():
    js = (ROOT / "site" / "static" / "commit.js").as_posix()
    script = (f"const m = require({json.dumps(js)});"
              f"const d = m.encodeCalls([{{token: '{TSLA}', p: 0.62}}, {{token: '{NVDA}', p: 0.5}}]);"
              f"console.log(m.calldata(120261113, d, ['bc_test1']));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout.strip()
    data = commits.encode_calls([Call(TSLA, 6200, None), Call(NVDA, 5000, None)])
    want = commits.commit_calldata(120261113, 1, data, attribution.to_suffix(["bc_test1"]))
    assert out == want
