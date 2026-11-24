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


SEND = """
const m = require(%s);
const seen = [];
const eth = { request: async ({ method, params }) => {
  seen.push({ method, params });
  if (method === "wallet_getCapabilities") return { "0x2105": {} };
  if (method === "wallet_sendCalls") return { id: "0xabc" };
  if (method === "wallet_getCallsStatus") return { receipts: [{ transactionHash: "0xhash" }] };
  if (method === "eth_sendTransaction") return "0xplain";
} };
(async () => {
  const st = { textContent: "" };
  const h = await m.send(eth, "0x1", "0x2105", "0xledger", 120261120, "00", ["bc_test1"], st, %s, %s, %s);
  console.log(JSON.stringify({ h, seen, st: st.textContent }));
})();
"""


def _send(paymaster, passkey, context=None):
    js = json.dumps((ROOT / "site" / "static" / "commit.js").as_posix())
    out = subprocess.run(["node", "-e", SEND % (js, json.dumps(paymaster), json.dumps(passkey), json.dumps(context))],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_passkey_wallet_sends_builder_code_and_sponsor():
    r = _send("https://paymaster.example", True)
    assert [s["method"] for s in r["seen"]][:1] == ["wallet_sendCalls"]   # no capability probe for a passkey wallet
    caps = r["seen"][0]["params"][0]["capabilities"]
    assert caps["dataSuffix"]["value"] == "0x" + attribution.to_suffix(["bc_test1"]).hex()
    assert caps["paymasterService"] == {"url": "https://paymaster.example"}
    assert r["h"] == "0xhash" and r["st"].startswith("Gas covered")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_wallet_without_capabilities_pays_its_own_gas_and_keeps_the_code():
    r = _send("https://paymaster.example", False)
    assert [s["method"] for s in r["seen"]] == ["wallet_getCapabilities", "eth_sendTransaction"]
    assert r["seen"][1]["params"][0]["data"].endswith("80218021802180218021802180218021")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_sponsorship_policy_goes_with_the_paymaster():
    r = _send("https://paymaster.example", True, {"sponsorshipPolicyId": "sp_test"})
    caps = r["seen"][0]["params"][0]["capabilities"]
    assert caps["paymasterService"] == {"url": "https://paymaster.example", "context": {"sponsorshipPolicyId": "sp_test"}}
