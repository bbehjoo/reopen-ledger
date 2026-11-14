#!/usr/bin/env node
/**
 * Reopen Ledger starter agent (Node 20+, one dependency: viem).
 *
 * Puts one record on the CallLedger contract on Base: commit(windowId, 1, data), where data holds one
 * probability per slate token that its Chainlink reference value ends the window above where it started.
 * The contract holds no funds and the transaction carries no value; it only emits an event.
 *
 *   npx tsx agent.ts --dry-run            print the window, the probabilities and the calldata; send nothing
 *   npx tsx agent.ts                      send the record (needs PRIVATE_KEY and a little ETH on Base for gas)
 *   npx tsx agent.ts --kind daily         only consider daily windows (kind 2); --kind closed for kind 1
 *   npx tsx agent.ts --window 220261117   a specific open window
 *   npx tsx agent.ts --dry-run --fixture  fixed example (no network), used by verify.py
 *
 * Env: PRIVATE_KEY (hex, the wallet that signs), BUILDER_CODES (yours, comma separated, optional),
 *      RPC_URL (default https://mainnet.base.org), FORM_URL (default the live site's data/form.json).
 *
 * The encoding is self-contained on purpose (copied from the site's commit.js, METHODS.md section 4), so this
 * file can be copied anywhere on its own.
 */
import { createPublicClient, createWalletClient, http, type Address, type Hex } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { base } from "viem/chains";

const FORM_URL = process.env.FORM_URL || "https://bbehjoo.github.io/reopen-ledger/data/form.json";
const RPC_URL = process.env.RPC_URL || "https://mainnet.base.org";
const EXPECTED_LEDGER = "0x32e9d4e3c865b802689d39caaa30c7328de281c0";
const CHAIN_ID = 8453;
const MARGIN_MS = 120_000; // leave two minutes for the transaction to be mined before the cutoff

interface Token { address: string; symbol: string; name?: string }
interface Window { id: number; label: string; cutoff_ms: number; cutoff_et: string }
interface Form {
  windows: Window[];
  slate: Token[];
  ledger: { address: string; chain_id: number } | null;
  builder_codes?: string[];
}

// =====================================================================================================
// YOUR MODEL GOES HERE.
// Return, for each slate token address, the probability (0 to 1) that its Chainlink reference value at the
// window's end is above its value at the window's start. Tokens you leave out are scored as 0.5.
// The default below says 0.5 for everything, which scores exactly like a coin flip.
// =====================================================================================================
async function predict(slate: Token[], _window: Window): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  for (const t of slate) out[t.address] = 0.5;
  return out;
}

// ---- encoding: commit(uint32,uint16,bytes), schema 1, plus the ERC-8021 attribution suffix ----
const SELECTOR = "eda6e22e"; // first 4 bytes of keccak256("commit(uint32,uint16,bytes)")
const MARKER = "80218021802180218021802180218021";
const RET_NONE = "80000000"; // no point call

function word(n: number | bigint): string { return BigInt(n).toString(16).padStart(64, "0"); }
function hexByte(n: number): string { return n.toString(16).padStart(2, "0"); }

/** 26 bytes per token, sorted by address: token (20) | p_up_bps uint16 | ret_bps int32 (none). */
function encodeCalls(calls: { token: string; p: number }[]): string {
  const sorted = calls.map((c) => ({ token: c.token.toLowerCase(), p: c.p }))
    .sort((a, b) => (a.token < b.token ? -1 : 1));
  const seen = new Set<string>();
  let h = "";
  for (const c of sorted) {
    if (!/^0x[0-9a-f]{40}$/.test(c.token)) throw new Error(`bad token address ${c.token}`);
    if (seen.has(c.token)) throw new Error(`duplicate token ${c.token}`);
    seen.add(c.token);
    if (!(c.p >= 0 && c.p <= 1)) throw new Error(`probability must be in [0, 1], got ${c.p} for ${c.token}`);
    const bps = Math.round(c.p * 10000);
    h += c.token.slice(2) + bps.toString(16).padStart(4, "0") + RET_NONE;
  }
  return h;
}

/** ERC-8021 schema 0: codes (ASCII, comma joined) | length (1 byte) | 0x00 | 0x8021 x 8. */
function suffix(codes: string[]): string {
  const raw = codes.join(",");
  if (!/^[\x20-\x7e]*$/.test(raw)) throw new Error("builder codes must be ASCII");
  if (raw.length > 255) throw new Error("builder codes too long (255 bytes at most)");
  let h = "";
  for (const ch of raw) h += hexByte(ch.charCodeAt(0));
  return h + hexByte(raw.length) + "00" + MARKER;
}

function calldata(windowId: number, dataHex: string, codes: string[]): Hex {
  const n = dataHex.length / 2;
  const padded = dataHex + "0".repeat((64 - (dataHex.length % 64)) % 64);
  return ("0x" + SELECTOR + word(windowId) + word(1) + word(96) + word(n) + padded
    + (codes.length ? suffix(codes) : "")) as Hex;
}

// ---- fixed example for verify.py: no network, nothing sent ----
const FIXTURE = {
  window: { id: 120261120, label: "fixture: closed 2026-11-20", cutoff_ms: 0, cutoff_et: "fixture" } as Window,
  slate: [
    { address: "0xb20000000000000000000078ee7ce2fe4908108c", symbol: "NVDAc" },
    { address: "0xb2000000000000000000001e800a7f5189430cd0", symbol: "TSLAc" },
  ] as Token[],
  probs: { "0xb20000000000000000000078ee7ce2fe4908108c": 0.62, "0xb2000000000000000000001e800a7f5189430cd0": 0.41 } as Record<string, number>,
  builderCodes: ["bc_test123"],
  projectCodes: ["bc_akq83qpj"],
};

function parseArgs(argv: string[]) {
  const a = { dryRun: false, fixture: false, kind: "any", window: 0 };
  for (let i = 0; i < argv.length; i++) {
    const x = argv[i];
    if (x === "--dry-run") a.dryRun = true;
    else if (x === "--fixture") a.fixture = true;
    else if (x === "--kind") a.kind = argv[++i] ?? "";
    else if (x === "--window") a.window = Number(argv[++i]);
    else throw new Error(`unknown argument ${x}`);
  }
  if (!["any", "closed", "daily"].includes(a.kind)) throw new Error("--kind must be closed, daily or any");
  if (a.window && !Number.isInteger(a.window)) throw new Error("--window needs a numeric window id");
  return a;
}

function splitCodes(s: string | undefined): string[] {
  return (s ?? "").split(",").map((c) => c.trim()).filter(Boolean);
}

function pickWindow(windows: Window[], kind: string, wanted: number, now: number): Window | undefined {
  const kindId = kind === "closed" ? 1 : kind === "daily" ? 2 : 0;
  return windows
    .filter((w) => w.cutoff_ms - now > MARGIN_MS)
    .filter((w) => !kindId || Math.floor(w.id / 100_000_000) === kindId)
    .filter((w) => !wanted || w.id === wanted)
    .sort((x, y) => x.cutoff_ms - y.cutoff_ms)[0];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  let window: Window, slate: Token[], probs: Record<string, number>, ledger: string, codes: string[];

  if (args.fixture) {
    if (!args.dryRun) throw new Error("--fixture only works with --dry-run");
    ({ window, slate, probs } = FIXTURE);
    ledger = EXPECTED_LEDGER;
    codes = [...FIXTURE.builderCodes, ...FIXTURE.projectCodes];
  } else {
    const r = await fetch(FORM_URL, { cache: "no-store" });
    if (!r.ok) throw new Error(`${FORM_URL}: HTTP ${r.status}`);
    const form = (await r.json()) as Form;
    if (!form.ledger) throw new Error("the contract is not deployed yet (form.json has no ledger)");
    if (form.ledger.chain_id !== CHAIN_ID) throw new Error(`unexpected chain id ${form.ledger.chain_id}`);
    if (form.ledger.address.toLowerCase() !== EXPECTED_LEDGER && !process.env.LEDGER_OVERRIDE) {
      throw new Error(`form.json names ledger ${form.ledger.address}, expected ${EXPECTED_LEDGER} (set LEDGER_OVERRIDE=1 to accept)`);
    }
    const w = pickWindow(form.windows, args.kind, args.window, Date.now());
    if (!w) {
      console.log("No window is open for records right now (or none matches --kind/--window). Nothing sent.");
      process.exitCode = 2;
      return;
    }
    window = w;
    slate = form.slate;
    ledger = form.ledger.address;
    const own = splitCodes(process.env.BUILDER_CODES);
    codes = [...own, ...(form.builder_codes ?? []).filter((c) => !own.includes(c))];
    probs = await predict(slate, window);
  }

  const onSlate = new Map(slate.map((t) => [t.address.toLowerCase(), t]));
  const calls = Object.entries(probs).map(([token, p]) => {
    if (!onSlate.has(token.toLowerCase())) throw new Error(`predict() returned a token that is not on the slate: ${token}`);
    return { token, p };
  });
  if (!calls.length) throw new Error("predict() returned no probabilities");
  const data = calldata(window.id, encodeCalls(calls), codes);

  console.log(`window   ${window.id}  ${window.label}  (records count until ${window.cutoff_et})`);
  for (const c of [...calls].sort((a, b) => (a.token.toLowerCase() < b.token.toLowerCase() ? -1 : 1))) {
    console.log(`p        ${onSlate.get(c.token.toLowerCase())!.symbol.padEnd(8)} ${c.token.toLowerCase()}  ${c.p.toFixed(4)}`);
  }
  console.log(`codes    ${codes.join(",") || "(none)"}`);
  console.log(`to       ${ledger}`);
  console.log(`calldata ${data}`);

  if (args.dryRun) { console.log("dry run: nothing sent"); return; }

  const pk = (process.env.PRIVATE_KEY ?? "").trim();
  if (!pk) throw new Error("PRIVATE_KEY is not set");
  const account = privateKeyToAccount((pk.startsWith("0x") ? pk : `0x${pk}`) as Hex);
  const wallet = createWalletClient({ account, chain: base, transport: http(RPC_URL) });
  const client = createPublicClient({ chain: base, transport: http(RPC_URL) });
  console.log(`from     ${account.address}`);
  const hash = await wallet.sendTransaction({ to: ledger as Address, data, value: 0n });
  console.log(`tx       ${hash}`);
  console.log(`basescan https://basescan.org/tx/${hash}`);
  const rc = await client.waitForTransactionReceipt({ hash });
  const block = await client.getBlock({ blockNumber: rc.blockNumber });
  const inTime = Number(block.timestamp) * 1000 <= window.cutoff_ms;
  console.log(`mined    block ${rc.blockNumber}, status ${rc.status}, ${inTime ? "before the cutoff: it counts" : "AFTER the cutoff: it will not be scored"}`);
  console.log("The first record per wallet and window is the scored one; it shows on the board after the window resolves.");
}

main().catch((e) => {
  console.error(`error: ${e instanceof Error ? e.message : e}`);
  process.exitCode = 1;
});
