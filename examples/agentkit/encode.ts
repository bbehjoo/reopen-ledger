// Calldata for CallLedger.commit(windowId, 1, data) plus the ERC-8021 Builder Code suffix (METHODS.md section 4).
// No dependencies, so it can be copied anywhere; verified byte for byte against the Python reference by
// tests/test_examples_encoding.py.
export const LEDGER = "0x32E9d4e3c865b802689D39caAA30c7328de281C0";
const SELECTOR = "eda6e22e"; // commit(uint32,uint16,bytes)
const MARKER = "80218021802180218021802180218021";
export const PROJECT_CODES = ["bc_akq83qpj"];

const word = (n: number | bigint) => BigInt(n).toString(16).padStart(64, "0");
const hexByte = (n: number) => n.toString(16).padStart(2, "0");

/** Your Builder Codes first, then the project's; both are kept and read. */
export function encode(windowId: number, calls: { token: string; p: number }[], builderCodes: string[]): `0x${string}` {
  const body = [...calls]
    .sort((a, b) => (a.token.toLowerCase() < b.token.toLowerCase() ? -1 : 1))
    .map((c) => c.token.toLowerCase().slice(2) + Math.round(c.p * 10000).toString(16).padStart(4, "0") + "80000000")
    .join("");
  const n = body.length / 2;
  const padded = body + "0".repeat((64 - (body.length % 64)) % 64);
  let data = SELECTOR + word(windowId) + word(1) + word(96) + word(n) + padded;
  const codes = [...builderCodes, ...PROJECT_CODES.filter((c) => !builderCodes.includes(c))];
  if (codes.length) {
    const raw = codes.join(",");
    data += [...raw].map((ch) => hexByte(ch.charCodeAt(0))).join("") + hexByte(raw.length) + "00" + MARKER;
  }
  return `0x${data}`;
}
