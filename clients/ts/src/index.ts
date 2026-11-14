/**
 * commitCalls: put a forecast on the record in the CallLedger contract on Base.
 *
 * A record is one transaction: `commit(windowId, 1, data)` where `data` is the schema-1 encoding of your
 * calls (one probability per token that the reference value ends the window above where it started, plus
 * an optional point call in basis points). Your own Builder Codes ride along in the ERC-8021 suffix, next
 * to this project's code, so your attribution is kept. The first record per wallet and window is the one
 * that is scored; later ones are shown, never scored. Windows, cutoffs and scoring: METHODS.md.
 *
 * Nothing here routes, quotes or executes anything: it writes one event to a contract that holds no funds.
 */
import type { Address, Hex, PublicClient, WalletClient } from "viem";

export const LEDGER_ABI = [
  {
    type: "function",
    name: "commit",
    stateMutability: "nonpayable",
    inputs: [
      { name: "windowId", type: "uint32" },
      { name: "schemaId", type: "uint16" },
      { name: "data", type: "bytes" },
    ],
    outputs: [],
  },
  {
    type: "event",
    name: "Committed",
    anonymous: false,
    inputs: [
      { name: "committer", type: "address", indexed: true },
      { name: "windowId", type: "uint32", indexed: true },
      { name: "schemaId", type: "uint16", indexed: true },
      { name: "data", type: "bytes", indexed: false },
    ],
  },
] as const;

export const SCHEMA_CALLS = 1;
export const KIND_CLOSED = 1; // weekend or holiday span, dated by the Eastern date it starts
export const KIND_DAILY = 2; // daily window, dated by its trading day
const RET_NONE = -2147483648;
const MARKER = "80218021802180218021802180218021";

export interface Call {
  /** official token address (see `isOfficialToken`) */
  token: Address;
  /** probability, 0..1, that the reference value at the window's end is above its value at the start */
  pUp: number;
  /** optional point call: expected log return over the window, in basis points */
  retBps?: number;
}

/** kind * 100000000 + yyyymmdd, with the date in US Eastern time. */
export function windowId(kind: number, isoDate: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!m) throw new Error(`bad date ${isoDate}`);
  return kind * 100_000_000 + Number(m[1]) * 10_000 + Number(m[2]) * 100 + Number(m[3]);
}

function hexOf(n: number, bytes: number, signed = false): string {
  let v = BigInt(n);
  if (signed && v < 0n) v = (1n << BigInt(8 * bytes)) + v;
  const s = v.toString(16);
  if (s.length > bytes * 2) throw new Error(`value ${n} does not fit ${bytes} bytes`);
  return s.padStart(bytes * 2, "0");
}

/** Schema-1 encoding: 26 bytes per token, sorted by address: token | p_up_bps uint16 | ret_bps int32. */
export function encodeCalls(calls: Call[]): Hex {
  const sorted = [...calls].sort((a, b) => (a.token.toLowerCase() < b.token.toLowerCase() ? -1 : 1));
  const seen = new Set<string>();
  let out = "0x";
  for (const c of sorted) {
    const t = c.token.toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(t)) throw new Error(`bad token address ${c.token}`);
    if (seen.has(t)) throw new Error(`duplicate token ${c.token}`);
    seen.add(t);
    if (!(c.pUp >= 0 && c.pUp <= 1)) throw new Error(`pUp must be in [0, 1], got ${c.pUp}`);
    const bps = Math.round(c.pUp * 10_000);
    const ret = c.retBps === undefined ? RET_NONE : Math.round(c.retBps);
    if (c.retBps !== undefined && (ret <= RET_NONE || ret > 2147483647)) throw new Error("retBps out of range");
    out += t.slice(2) + hexOf(bps, 2) + hexOf(ret, 4, true);
  }
  return out as Hex;
}

export function decodeCalls(data: Hex): Call[] {
  const h = data.slice(2);
  if (h.length % 52) throw new Error("schema 1 data length is not a multiple of 26 bytes");
  const out: Call[] = [];
  for (let i = 0; i < h.length; i += 52) {
    const e = h.slice(i, i + 52);
    let r = parseInt(e.slice(44, 52), 16);
    if (r >= 2 ** 31) r -= 2 ** 32;
    out.push({ token: ("0x" + e.slice(0, 40)) as Address, pUp: parseInt(e.slice(40, 44), 16) / 10_000,
      ...(r === RET_NONE ? {} : { retBps: r }) });
  }
  return out;
}

/** ERC-8021 schema-0 suffix: codes (ASCII, comma-joined) | length (1 byte) | 0x00 | 0x8021 x 8. */
export function attributionSuffix(codes: string[]): Hex {
  const raw = codes.join(",");
  if (!/^[\x20-\x7e]*$/.test(raw)) throw new Error("builder codes must be ASCII");
  if (raw.length > 255) throw new Error("builder codes too long");
  let h = "0x";
  for (const ch of raw) h += ch.charCodeAt(0).toString(16).padStart(2, "0");
  return (h + hexOf(raw.length, 1) + "00" + MARKER) as Hex;
}

export interface CommitOptions {
  wallet: WalletClient;
  ledger: Address;
  windowId: number;
  calls: Call[];
  /** your Builder Codes; this project's code (`projectCode`) is added after them when given */
  builderCodes?: string[];
  projectCode?: string;
}

/** Sends one commit transaction; returns its hash. */
export async function commitCalls(o: CommitOptions): Promise<Hex> {
  if (!o.wallet.account) throw new Error("wallet client needs an account");
  const codes = [...(o.builderCodes ?? []), ...(o.projectCode ? [o.projectCode] : [])];
  return o.wallet.writeContract({
    address: o.ledger,
    abi: LEDGER_ABI,
    functionName: "commit",
    args: [o.windowId, SCHEMA_CALLS, encodeCalls(o.calls)],
    account: o.wallet.account,
    chain: o.wallet.chain,
    ...(codes.length ? { dataSuffix: attributionSuffix(codes) } : {}),
  });
}

/** Your records for a window, read back from the chain (first one is the scored one). */
export async function recordsFor(client: PublicClient, ledger: Address, committer: Address, window: number,
  fromBlock: bigint) {
  const logs = await client.getLogs({
    address: ledger,
    event: LEDGER_ABI[1],
    args: { committer, windowId: window, schemaId: SCHEMA_CALLS },
    fromBlock,
  });
  return logs.map((l) => ({ tx: l.transactionHash, block: l.blockNumber, calls: decodeCalls(l.args.data as Hex) }));
}

export { OFFICIAL_TOKENS, isOfficialToken } from "./tokens.js";
