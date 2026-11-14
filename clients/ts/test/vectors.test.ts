import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { encodeFunctionData, type Hex } from "viem";
import { attributionSuffix, decodeCalls, encodeCalls, isOfficialToken, LEDGER_ABI, windowId } from "../src/index.js";

const here = dirname(fileURLToPath(import.meta.url));
const v = JSON.parse(readFileSync(join(here, "..", "..", "..", "vectors", "vectors.json"), "utf8"));

test("schema-1 encoding matches the Python vectors", () => {
  for (const c of v.calls) {
    const calls = c.calls.map((x: any) => ({ token: x.token, pUp: x.p_up_bps / 10_000,
      ...(x.ret_bps === null ? {} : { retBps: x.ret_bps }) }));
    assert.equal(encodeCalls(calls), c.data);
    const back = decodeCalls(c.data);
    assert.equal(back.length, calls.length);
  }
});

test("attribution suffix matches the Python vectors and the ox example", () => {
  for (const s of v.suffixes) assert.equal(attributionSuffix(s.codes), s.suffix);
});

test("window ids match", () => {
  for (const w of v.windows) assert.equal(windowId(w.kind, w.date), w.id);
});

test("full calldata with suffix matches", () => {
  const c = v.commit_calldata;
  const body = encodeFunctionData({ abi: LEDGER_ABI, functionName: "commit", args: [c.window, c.schema, c.data as Hex] });
  assert.equal(body + attributionSuffix(c.codes).slice(2), c.calldata);
});

test("rejects bad input", () => {
  assert.throws(() => encodeCalls([{ token: "0x1234" as any, pUp: 0.5 }]));
  assert.throws(() => encodeCalls([{ token: "0xb20000000000000000000078ee7ce2fe4908108c", pUp: 1.2 }]));
});

test("official token registry", () => {
  assert.equal(isOfficialToken("0xb20000000000000000000078ee7ce2fE4908108C"), true);
  assert.equal(isOfficialToken("0x0000000000000000000000000000000000000001"), false);
});
