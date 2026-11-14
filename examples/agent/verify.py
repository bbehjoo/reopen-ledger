"""Byte-equality check: agent.py and agent.ts against the repository's own encoder (callrec).

Run from the repository root:

    uv run --with web3 --with eth-account python examples/agent/verify.py          # fixture only
    uv run --with web3 --with eth-account python examples/agent/verify.py --live   # also live form.json

Needs `npm i` inside examples/agent first. Sends nothing to any network; --live only reads form.json.

Fixture: window 120261120, NVDAc p = 0.62, TSLAc p = 0.41, codes ["bc_test123"] then ["bc_akq83qpj"].
Reference: callrec.commits.commit_calldata(window, 1, encode_calls(...), housecommit.suffix_for(...)).
Also compared: eth_abi (web3's ABI encoder) and viem's encodeFunctionData, each plus the suffix.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from callrec import attribution, commits, housecommit  # noqa: E402

WINDOW = 120261120
NVDA = "0xb20000000000000000000078ee7ce2fe4908108c"
TSLA = "0xb2000000000000000000001e800a7f5189430cd0"
OWN, PROJECT = ["bc_test123"], ["bc_akq83qpj"]


def calldata_of(out: str) -> str:
    m = re.search(r"^calldata (0x[0-9a-f]+)\s*$", out, re.MULTILINE)
    if not m:
        raise SystemExit("no calldata line in output:\n" + out)
    return m.group(1)


def run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} exited {r.returncode}:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def npx() -> str:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise SystemExit("npx not found: install Node 20+")
    return exe


def main() -> int:
    data = commits.encode_calls([commits.Call(NVDA, 6200, None), commits.Call(TSLA, 4100, None)])
    sfx = housecommit.suffix_for({"builder_code": OWN[0]}, PROJECT)   # own code first, then the project's
    ref = commits.commit_calldata(WINDOW, commits.SCHEMA_CALLS, data, sfx)

    assert attribution.from_calldata(ref) == OWN + PROJECT, attribution.from_calldata(ref)
    assert sfx == attribution.to_suffix(OWN + PROJECT)

    results = {
        "agent.py": calldata_of(run([sys.executable, "agent.py", "--dry-run", "--fixture"])),
        "agent.ts": calldata_of(run([npx(), "tsx", "agent.ts", "--dry-run", "--fixture"])),
    }

    import eth_abi  # ships with web3
    from eth_utils import keccak
    sel = keccak(text=commits.COMMIT_SIG)[:4].hex()
    results["eth_abi"] = "0x" + sel + eth_abi.encode(["uint32", "uint16", "bytes"], [WINDOW, 1, data]).hex() + sfx.hex()

    viem_js = ("import { encodeFunctionData, parseAbi } from 'viem';"
               "const [w, d, s] = process.argv.slice(1);"
               "const abi = parseAbi(['function commit(uint32 windowId, uint16 schemaId, bytes data)']);"
               "console.log('calldata ' + encodeFunctionData({ abi, functionName: 'commit', args: [Number(w), 1, d] }) + s);")
    results["viem"] = calldata_of(run(["node", "--input-type=module", "-e", viem_js, "--",
                                       str(WINDOW), "0x" + data.hex(), sfx.hex()]))

    # the record decodes back to what was put in
    body = bytes.fromhex(ref[2:])[: -len(sfx)]
    n = int.from_bytes(body[4 + 96: 4 + 128], "big")
    decoded = commits.decode_calls(body[4 + 128: 4 + 128 + n])
    assert [(c.token, c.p_up_bps, c.ret_bps) for c in decoded] == [(TSLA, 4100, None), (NVDA, 6200, None)], decoded
    assert int.from_bytes(body[4:36], "big") == WINDOW and int.from_bytes(body[36:68], "big") == 1

    print(f"reference (callrec) {ref}")
    ok = True
    for name, cd in results.items():
        same = cd == ref
        ok &= same
        print(f"{name:<10} {'PASS' if same else 'FAIL'}" + ("" if same else f"  {cd}"))

    if "--live" in sys.argv[1:]:
        py = calldata_of(run([sys.executable, "agent.py", "--dry-run", "--kind", "daily"]))
        ts = calldata_of(run([npx(), "tsx", "agent.ts", "--dry-run", "--kind", "daily"]))
        same = py == ts
        ok &= same
        print(f"{'live':<10} {'PASS' if same else 'FAIL'}  agent.py and agent.ts on live form.json ({len(py) // 2 - 1} bytes)")

    print("ALL PASS" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
